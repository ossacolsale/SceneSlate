"""Self-contained Lua script body; embedded into every exported package."""
LUA=r'''
-- Experimental only. Read the audit report before changing these settings.
local APPLY = true
-- 08_TEST_SYNC_NATIVO: 25 fps, same sign, fractional Resolve frame offsets.
local OFFSET_SIGN = 1
-- If WAV FPS is unavailable, project FPS is an experimental fallback.
-- The resulting marker attachment must pass readback before acceptance.
local AUDIO_MARKER_FPS = 25
local MARKER_VALIDATED = true

local function call(obj, method, ...)
    if not obj then return nil end
    local ok, value = pcall(function(...) return obj[method](obj, ...) end, ...)
    if ok then return value end
    return nil
end
local function prop(item,key)
    local x=call(item,"GetClipProperty",key)
    if x==nil then return "" end
    return tostring(x)
end
local function id(item)
    local v=call(item,"GetUniqueId") or call(item,"GetMediaId")
    return v and tostring(v) or ""
end
local function norm(path)
    local s=tostring(path or ""):gsub("\\","/"):gsub("/+","/")
    if package.config:sub(1,1)=="\\" then s=s:lower() end
    return s
end
local function basename(path)
    return tostring(path):gsub("\\","/"):match("([^/]+)$") or ""
end
local function number(s)
    if type(s)=="number" then return s end
    local a,b=tostring(s):match("^%s*(%d+)%s*/%s*(%d+)%s*$")
    if a and tonumber(b)>0 then return tonumber(a)/tonumber(b) end
    local v=tonumber((tostring(s):gsub(',', '.')))
    if v and v==v and math.abs(v)<math.huge then return v end
    return nil
end
local function fps_of(item)
    local n=number(prop(item,"FPS"))
    if n==23.976 or n==23.98 then return 24000/1001 end
    if n==29.97 then return 30000/1001 end
    if n==59.94 then return 60000/1001 end
    return n
end
local function nearest(n)
    if n>=0 then return math.floor(n+.5) end
    return math.ceil(n-.5)
end
local function nonempty(v)
    return v~="" and v~="None" and v~="N/A" and v~="-"
end
local source=debug.getinfo(1,"S").source
assert(source:sub(1,1)=="@","Run the saved Lua file using dofile, not pasted text.")
local directory=source:sub(2):match("^(.*[/\\])") or "./"
local r=resolve
if not r and bmd then r=bmd.scriptapp("Resolve") end
assert(r,"Resolve internal Lua console required")
local project=call(call(r,"GetProjectManager"),"GetCurrentProject")
assert(project,"Open the test project first")
local pool=call(project,"GetMediaPool")
local root=call(pool,"GetRootFolder")
assert(root,"Media Pool unavailable")
local project_id=call(project,"GetUniqueId") or call(pool,"GetUniqueId")
local report=assert(io.open(directory.."sync_report.tsv","a"))
local function clean(v)
    return tostring(v==nil and "" or v):gsub("[\t\r\n]"," ")
end
local function log(row,state,reason,v,a,err)
    local cols={os.date("!%Y-%m-%dT%H:%M:%SZ"),row.id or "",row.label or "",
        state,reason or "",id(v),id(a),prop(v,"File Path"),prop(a,"File Path"),
        prop(v,"FPS"),prop(a,"FPS"),prop(v,"Audio Offset"),prop(v,"Synced Audio"),
        tostring(row.offset or ""),tostring(err or ""),prop(v,"Audio Ch"),
        tostring(call(v,"GetAudioMapping") or "")}
    for i,x in ipairs(cols) do cols[i]=clean(x) end
    report:write(table.concat(cols,"\t"),"\n");report:flush()
    print((row.label or "SceneSlate").." | "..state.." | "..(reason or ""))
end
report:write("utc\tassociation\tlabel\tstate\treason\tvideo_id\taudio_id\tvideo_path\taudio_path\tvideo_fps\taudio_fps\tresolve_audio_offset_raw\tsynced_audio_raw\tcatalog_offset_s\terror_ms\tvideo_audio_channels\taudio_mapping_raw\n")
local function clips(folder)
    return call(folder,"GetClipList") or {}
end
local function children(folder)
    return call(folder,"GetSubFolderList") or {}
end
local function child(folder,name)
    local found=nil
    for _,f in pairs(children(folder)) do
        if call(f,"GetName")==name then
            if found then return nil end
            found=f
        end
    end
    return found
end
local roots={}
local all_ids={}
local id_count={}
local basename_paths={}
local function walk(folder)
    if call(folder,"GetName")==manifest.root then
        roots[#roots+1]=folder
    end
    for _,item in pairs(clips(folder)) do
        local k=id(item);if k~="" then all_ids[k]=true;id_count[k]=(id_count[k] or 0)+1 end
        local path=norm(prop(item,"File Path"))
        if path~="" then
            local name=norm(basename(path))
            basename_paths[name]=basename_paths[name] or {}
            basename_paths[name][path]=true
        end
    end
    for _,f in pairs(children(folder)) do walk(f) end
end
walk(root)
-- Some MAM importers wrap the XML in a same-named project bin.
local candidates={}
for _,f in ipairs(roots) do
    local has_scene=false
    for _,sub in pairs(children(f)) do
        if tostring(call(sub,"GetName") or ""):match("^Scen[ae] %d+") then has_scene=true end
    end
    if has_scene then candidates[#candidates+1]=f end
end
if #candidates~=1 then
    log({},"BLOCKED","Expected exactly one package root containing scene bins; import MAM once.")
    report:close();return
end
local package_root=candidates[1]
project_id=project_id or call(package_root,"GetUniqueId")
local function find_folder(names,create)
    local folder=package_root
    for i=2,#names do
        local f=child(folder,names[i])
        if not f and create then
            -- Do not create a second same-name folder if lookup was ambiguous.
            local n=0
            for _,other in pairs(children(folder)) do
                if call(other,"GetName")==names[i] then n=n+1 end
            end
            if n>0 then return nil end
            f=call(pool,"AddSubFolder",folder,names[i])
        end
        if not f then return nil end
        folder=f
    end
    return folder
end
local function key_for(row,kind)
    return row.id..":"..kind
end
local claimed={}
local need={}
for _,row in ipairs(manifest.rows) do
    for _,kind in ipairs({"video","audio"}) do
        local med=row[kind]
        if med and med.available then
            local key=table.concat(row.bins,"/").."|"..norm(med.path)
            need[key]=(need[key] or 0)+1
        end
    end
end
-- Per-project attempt journal: a partial mutation is never repeated silently.
local journal={}
local statepath=directory.."sync_state.tsv"
local old=io.open(statepath,"r")
if old then
    for line in old:lines() do
        local pid,key,status,vid,aid=line:match("^([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]*)\t([^\t]*)$")
        if pid and pid==tostring(project_id) then journal[key]={status=status,v=vid,a=aid} end
    end
    old:close()
end
local function save(row,status,v,a)
    local file=assert(io.open(statepath,"a"))
    local vi,ai=id(v),id(a)
    file:write(clean(project_id),"\t",row.id,"\t",status,"\t",vi,"\t",ai,"\n")
    file:flush();file:close()
    journal[row.id]={status=status,v=vi,a=ai}
end
local function locate(row,kind,folder,allow_import)
    local med=row[kind]
    if not med or not med.available then return nil,"source missing" end
    if not folder then return nil,"bin missing" end
    local matches,exact={},{}
    local previous=journal[row.id]
    local wanted=previous and (kind=="video" and previous.v or previous.a)
    for _,item in pairs(clips(folder)) do
        local uid=id(item)
        if uid~="" and id_count[uid]==1 and norm(prop(item,"File Path"))==norm(med.path) and not claimed[uid] then
            if wanted and wanted~="" and uid==wanted then return item end
            matches[#matches+1]=item
            if call(item,"GetName")==med.alias or prop(item,"Clip Name")==med.alias then exact[#exact+1]=item end
        end
    end
    if wanted and wanted~="" then return nil,"recorded ID absent in expected bin" end
    if #exact==1 then return exact[1] end
    if #exact>1 then return nil,"duplicate alias; inspect before proceeding" end
    local key=table.concat(row.bins,"/").."|"..norm(med.path)
    if #matches==1 and need[key]==1 then return matches[1] end
    if not allow_import then return nil,"missing or ambiguous path/alias; independent import required" end
    if #matches>0 then return nil,"ambiguous existing identities; no automatic duplicate" end
    if call(pool,"SetCurrentFolder",folder)~=true then return nil,"cannot select import bin" end
    local result=call(pool,"ImportMedia",{med.path})
    local fresh={}
    for _,item in pairs(result or {}) do
        local uid=id(item)
        if uid~="" and not all_ids[uid] and norm(prop(item,"File Path"))==norm(med.path) then
            for _,candidate in pairs(clips(folder)) do
                if id(candidate)==uid then fresh[#fresh+1]=candidate end
            end
        end
    end
    if #fresh~=1 then return nil,"ImportMedia did not yield one distinct ID in target bin" end
    all_ids[id(fresh[1])]=true;id_count[id(fresh[1])]=1
    local bn=norm(basename(med.path));basename_paths[bn]=basename_paths[bn] or {}
    basename_paths[bn][norm(med.path)]=true
    return fresh[1]
end
local function synced_matches(item,audio)
    local raw=prop(item,"Synced Audio")
    if not nonempty(raw) then return false end
    if norm(raw)==norm(audio.path) or raw==audio.alias then return true end
    if norm(basename(raw))~=norm(basename(audio.path)) then return false end
    local paths=basename_paths[norm(basename(audio.path))] or {}
    local n=0
    for _ in pairs(paths) do n=n+1 end
    return n==1 and paths[norm(audio.path)]==true
end
local function offset_error(row,v)
    local vf=fps_of(v)
    local raw=number(prop(v,"Audio Offset"))
    if not vf or vf<=0 or raw==nil or not OFFSET_SIGN or row.offset==nil then return nil end
    return (raw*OFFSET_SIGN/vf-row.offset)*1000
end
local function settings(mode)
    local m=r.AUDIO_SYNC_MODE
    local e=r.AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO
    local v=r.AUDIO_SYNC_RETAIN_VIDEO_METADATA
    local ch=r.AUDIO_SYNC_CHANNEL_NUMBER
    if m==nil or e==nil or v==nil or mode==nil or ch==nil then return nil end
    return {[m]=mode,[e]=true,[v]=true,[ch]=1}
end
local function marker_sync(row,v,a)
    if not MARKER_VALIDATED then return false,"marker API not calibrated" end
    local st=settings(r.AUDIO_SYNC_MARKER)
    if not st then return false,"marker mode unavailable" end
    -- Marker-only mode can choose an existing marker unpredictably. Do not
    -- touch or compete with any user marker on either source item.
    local vm,am=call(v,"GetMarkers"),call(a,"GetMarkers")
    if type(vm)~="table" or type(am)~="table" then return false,"marker inspection failed" end
    if next(vm) or next(am) then return false,"existing markers; manual review required" end
    local vf,af=fps_of(v),fps_of(a) or AUDIO_MARKER_FPS
    if not vf or vf<=0 or not af or af<=0 then return false,"marker FPS unknown" end
    local rounded=nearest(row.offset*vf)/vf
    local start=math.max(0,-rounded)
    local finish=math.min(row.video.duration,row.audio.duration-rounded)
    -- Pick a common interior point; test nearby video frames to minimize
    -- audio-marker quantization and stay inside both files.
    local best=nil
    local first=math.ceil(start*vf)
    for vi=first,first+math.min(100,math.floor((finish-start)*vf)) do
        local at=vi/vf+rounded
        local ai=nearest(at*af)
        local vn,an=number(prop(v,"Frames")),number(prop(a,"Frames"))
        if vi>=0 and ai>=0 and vi/vf<row.video.duration and ai/af<row.audio.duration
            and (not vn or vi<vn) and (not an or ai<an) then
            local err=math.abs(ai/af-vi/vf-rounded)
            if not best or err<best.err then best={vi=vi,ai=ai,err=err} end
        end
    end
    if not best or best.err>0.5/vf+1e-8 then return false,"no safe marker pair within half a source frame" end
    local token="SceneSlate-"..row.id
    local made_v,made_a=false,false
    local function remove(item,frame)
        local mk=call(item,"GetMarkers")
        if type(mk)=="table" and mk[frame] and mk[frame].customData==token then
            call(item,"DeleteMarkerAtFrame",frame)
        end
    end
    made_v=call(v,"AddMarker",best.vi,"Blue",token,"Temporary SceneSlate sync",1,token)==true
    if made_v then made_a=call(a,"AddMarker",best.ai,"Blue",token,"Temporary SceneSlate sync",1,token)==true end
    local ok=false
    if made_v and made_a then ok=call(pool,"AutoSyncAudio",{v,a},st)==true end
    remove(v,best.vi);remove(a,best.ai)
    return ok,string.format("target rounded to %.6f s; theoretical residual %.3f ms; marker grid %.3f ms",rounded,(rounded-row.offset)*1000,best.err*1000)
end
local previous_folder=call(pool,"GetCurrentFolder")
local function rename_item(item,med,row)
    if not item then return end
    call(item,'SetClipProperty','Clip Name',med.alias)
    call(item,'SetMetadata','Comments','SceneSlate '..row.id..' | '..med.path..' | '..table.concat(row.descriptions,' | '))
    local color=({[1]='Green',[2]='Yellow',[3]='Red',[4]='Blue',[5]='Orange'})[row.category]
    if color then call(item,'SetClipColor',color) end
end
local function run_row(row)
    local folder=find_folder(row.bins,false)
    local before=journal[row.id]
    local v,ve,a,ae
    if row.video then v,ve=locate(row,"video",folder,false) end
    if row.audio then a,ae=locate(row,"audio",folder,false) end
    if v then claimed[id(v)]=key_for(row,"video") end
    if a then claimed[id(a)]=key_for(row,"audio") end
    if not APPLY then
        log(row,"AUDIT",(ve or "").." "..(ae or ""),v,a)
        return
    end
    if before then
        log(row,"SKIP_JOURNAL",before.status.."; previous attempt never repeated automatically",v,a,offset_error(row,v))
        return
    end
    -- Guard all mutation on a calibrated sign and stable project identity.
    if not project_id or tostring(project_id)=="" or (OFFSET_SIGN~=1 and OFFSET_SIGN~=-1) then
        log(row,"BLOCKED","calibrate sign and verify project identity first",v,a);return
    end
    if row.status~="OK" or not row.video or not row.audio then
        -- Never call AutoSyncAudio for these rows.
        if (row.video and row.video.available) or (row.audio and row.audio.available) then
            if not folder then folder=find_folder(row.bins,true) end
            if folder then
                save(row,"START",v,a)
                if row.video and row.video.available and not v then v,ve=locate(row,"video",folder,true) end
                if row.audio and row.audio.available and not a then a,ae=locate(row,"audio",folder,true) end
                if v then claimed[id(v)]=key_for(row,"video");rename_item(v,row.video,row) end
                if a then claimed[id(a)]=key_for(row,"audio");rename_item(a,row.audio,row) end
                save(row,"NO_SYNC",v,a)
            end
        end
        log(row,row.status=="SINGLE" and "SINGLE" or "REVIEW","no automatic sync requested; "..(ve or "").." "..(ae or ""),v,a);return
    end
    if not folder then folder=find_folder(row.bins,true) end
    if not folder then log(row,"REVIEW","target bin unavailable",v,a);return end
    -- Journal before any possible import; incomplete attempts require inspection.
    save(row,"START",v,a)
    if not v then v,ve=locate(row,"video",folder,true) end
    if not a then a,ae=locate(row,"audio",folder,true) end
    if not v or not a or id(v)==id(a) then
        save(row,"REVIEW_IDENTITY",v,a);log(row,"REVIEW_IDENTITY",(ve or "").." "..(ae or ""),v,a);return
    end
    claimed[id(v)]=key_for(row,"video");claimed[id(a)]=key_for(row,"audio")
    save(row,"BOUND",v,a)
    local vf=fps_of(v)
    local source_fps=number(row.video.fps)
    if not vf or not source_fps or math.abs(vf-source_fps)>.005 then
        save(row,"REVIEW_FPS",v,a);log(row,"REVIEW_FPS","source FPS differs or unavailable",v,a);return
    end
    if nonempty(prop(v,"Synced Audio")) then
        local err=offset_error(row,v)
        local channels=number(prop(v,"Audio Ch"))
        local ok=synced_matches(v,row.audio) and err and math.abs(err)<=500/vf+1e-7
            and channels==row.video.channels+row.audio.channels
        save(row,ok and "EXISTING_OK" or "REVIEW_EXISTING",v,a)
        log(row,ok and "EXISTING_OK" or "REVIEW_EXISTING","pre-existing sync preserved",v,a,err);return
    end
    -- Best-effort labels, but original File Path is never changed.
    rename_item(v,row.video,row)
    rename_item(a,row.audio,row)
    local mode="marker"
    local detail=""
    local original_tc=prop(v,"Start TC")
    local original_channels=number(prop(v,"Audio Ch")) or row.video.channels
    local function verified(err)
        local after=number(prop(v,"Audio Ch"))
        local tc=prop(v,"Start TC")
        return synced_matches(v,row.audio) and err and math.abs(err)<=500/vf+1e-7
            and (not nonempty(original_tc) or tc==original_tc)
            and (after and after==original_channels+row.audio.channels)
    end
    if row.method~="manual" then
        local st=settings(r.AUDIO_SYNC_WAVEFORM)
        if st then
            mode="waveform";call(pool,"AutoSyncAudio",{v,a},st)
            local err=offset_error(row,v)
            if verified(err) then
                save(row,"OK_WAVEFORM",v,a);log(row,"OK_WAVEFORM","readback within half source frame",v,a,err);return
            end
            if nonempty(prop(v,"Synced Audio")) then
                -- Reimport an independent item; never sync the attached item twice.
                -- MoveClips is documented but this quarantine flow needs real validation.
                local review=child(package_root,"99 – Sync diagnostics")
                if not review then review=call(pool,"AddSubFolder",package_root,"99 – Sync diagnostics") end
                local quarantine=review and (child(review,row.id) or call(pool,"AddSubFolder",review,row.id))
                local old_id=id(v)
                if not quarantine or call(pool,"MoveClips",{v},quarantine)~=true then
                    save(row,"REVIEW_WAVEFORM_ATTACHED",v,a)
                    log(row,"REVIEW_WAVEFORM_ATTACHED","cannot quarantine attached attempt",v,a,err);return
                end
                local moved=false
                for _,item in pairs(clips(quarantine)) do if id(item)==old_id then moved=true end end
                if not moved then
                    save(row,"REVIEW_WAVEFORM_ATTACHED",v,a);log(row,"REVIEW_WAVEFORM_ATTACHED","quarantine ID not verified",v,a,err);return
                end
                log(row,"QUARANTINED_WAVEFORM","out-of-tolerance attachment retained separately",v,a,err)
                save(row,"REIMPORT_PENDING",nil,a)
                local new,why=locate(row,"video",folder,true)
                if not new or id(new)==old_id or nonempty(prop(new,"Synced Audio")) then
                    save(row,"REVIEW_REIMPORT",nil,a);log(row,"REVIEW_REIMPORT",why or "fresh video not independent",new,a);return
                end
                v=new;claimed[id(v)]=key_for(row,"video")
                save(row,"BOUND_FALLBACK",v,a)
                original_tc=prop(v,"Start TC");original_channels=number(prop(v,"Audio Ch")) or row.video.channels
                if not fps_of(v) or math.abs(fps_of(v)-vf)>.005 then
                    save(row,"REVIEW_FPS",v,a);log(row,"REVIEW_FPS","reimported source FPS differs",v,a);return
                end
                rename_item(v,row.video,row)
            end
        end
    end
    local ok,msg=marker_sync(row,v,a)
    local err=offset_error(row,v)
    local valid=ok and verified(err)
    save(row,valid and "OK_MARKER" or "REVIEW_MARKER",v,a)
    log(row,valid and "OK_MARKER" or "REVIEW_MARKER",msg,v,a,err)
end
for _,row in ipairs(manifest.rows) do
    local ok,err=pcall(run_row,row)
    if not ok then log(row,"ERROR",tostring(err)) end
end
if previous_folder and APPLY then call(pool,"SetCurrentFolder",previous_folder) end
report:close()
print("SceneSlate: report saved to "..directory.."sync_report.tsv")
'''
