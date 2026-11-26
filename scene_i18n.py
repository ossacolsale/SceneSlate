"""SceneSlate UI localisation. Catalog JSON keys and stable option IDs are never translated."""
from __future__ import annotations

LANGUAGES = {'en': 'English', 'it': 'Italiano'}
# English is the default for a new profile. The left-hand strings come from the
# original Italian UI; keeping them stable preserves existing catalog semantics.
_PAIRS = r'''
Lingua:|||Language:
Nome A → Z|||Name A → Z
Nome Z → A|||Name Z → A
Data ↑ (meno recente)|||Date ↑ (oldest first)
Data ↓ (più recente)|||Date ↓ (newest first)
VIDEO  /  FILESYSTEM|||VIDEO / FILESYSTEM
AUDIO  /  FILESYSTEM|||AUDIO / FILESYSTEM
Associa / abbina →|||Attach / pair →
Sfoglia…|||Browse…
Vai|||Go
Filtra:|||Filter:
Ordina:|||Sort:
Solo non associati|||Unassigned only
Evidenzia liberi|||Highlight unassigned
Sottocartelle|||Subfolders
Tutti i file|||All files
Nome|||Name
Dimensione|||Size
Creazione*|||Created*
Tipo|||Type
Catalogazione riprese  •  Associazioni video/audio  •  Export Resolve|||Footage logging  •  Video/audio pairing  •  Resolve export
Nuovo|||New
Apri…|||Open…
Salva|||Save
Salva con nome…|||Save as…
Esporta…|||Export…
↶ Annulla|||↶ Undo
SCENE / SHOT / INQUADRATURE|||SCENES / SHOTS / ANGLES
Convenzione…|||Naming…
+ Scena|||+ Scene
+ Shot|||+ Shot
+ Sotto-shot|||+ Sub-shot
− Elimina|||− Delete
Rinumera…|||Renumber…
Copia contenuto  (Ctrl+C)|||Copy content (Ctrl+C)
Incolla qui  (Ctrl+V)|||Paste here (Ctrl+V)
Rinomina / Rinumera…|||Rename / Renumber…
Elimina…|||Delete…
⧉ Copia contenuto|||⧉ Copy content
↳ Incolla nella selezione|||↳ Paste into selection
Ctrl+C / Ctrl+V nella struttura|||Ctrl+C / Ctrl+V in the scene tree
Solo elementi senza file|||Only items without media
Solo non sincronizzati|||Unsynced only
Evidenzia vuoti|||Highlight empty
CIAK E ABBINAMENTI|||TAKES AND PAIRS
CIAK E ABBINAMENTI / SELEZIONA UNO SHOT|||TAKES AND PAIRS / SELECT A SHOT
+ Ciak|||+ Take
N° ciak…|||Take #…
↻ Auto|||↻ Auto
− Ciak|||− Take
Ciak|||Take
← VIDEO|||← VIDEO
AUDIO →|||AUDIO →
− File sul lato|||− File on selected side
Qualifica lato attivo:|||Selected side rating:
B · Buona|||G · Good
R · Riserva|||R · Reserve
S · Scarto|||X · Reject
←/→ sceglie VIDEO o AUDIO; ↑/↓ sceglie il ciak; B/R/S cambia la qualifica. F4: riproduci video. Trascina un file sulla riga per abbinarlo.|||←/→ selects VIDEO or AUDIO; ↑/↓ selects the take; G/R/X changes its rating. F4: play video. Drop a file onto a row to pair it.
Descrizione ciak:|||Take description:
Annotazioni ciak:|||Take notes:
Descrizione scena:|||Scene description:
Descrizione shot:|||Shot description:
Descrizione sotto-shot:|||Sub-shot description:
Lato attivo: VIDEO|||Active side: VIDEO
Lato attivo: AUDIO|||Active side: AUDIO
Lato attivo: |||Active side: 
Pronto. Crea una scena, seleziona uno shot e trascinaci video o audio.|||Ready. Create a scene, select a shot, and drag video or audio files onto it.
Seleziona prima uno shot.|||Select a shot first.
Seleziona prima una scena o un suo shot.|||Select a scene or one of its shots first.
Seleziona prima lo shot che conterrà il sotto-shot.|||First select the shot that will contain the sub-shot.
Seleziona scena, shot o sotto-shot da copiare.|||Select a scene, shot or sub-shot to copy.
Contenuto copiato negli appunti interni. Seleziona una destinazione e premi Ctrl+V.|||Content copied to the internal clipboard. Select a destination and press Ctrl+V.
Copia prima una scena, uno shot o un sotto-shot e seleziona la destinazione.|||Copy a scene, shot or sub-shot first, then select a destination.
 Nessun file originale è stato duplicato.||| No original media files were duplicated.
Impossibile incollare|||Cannot paste
Seleziona uno shot|||Select a shot
Seleziona uno shot a sinistra (es. Scena 1 / Shot 1) prima di associare i file.|||Select a shot on the left (e.g. Scene 1 / Shot 1) before attaching files.
Scena richiesta|||Scene required
Scena|||Scene
Sotto-shot|||Sub-shot
Inquadratura |||Angle 
 ciak||| takes
 shot||| shots
 sotto-shot||| sub-shots
 senza file||| without media
 vuoto||| empty
 non associati||| unassigned
 · ● = libero||| · ● = unassigned
 · m = data modifica (creazione non disponibile)||| · m = modified date (creation date unavailable)
Impossibile leggere la cartella: |||Unable to read folder: 
Non è una cartella.|||Not a directory.
Cartella non accessibile|||Folder inaccessible
Seleziona cartella |||Choose folder 
Associa allo shot|||Attach to shot
Seleziona uno o più file, poi usa “Associa allo shot”.|||Select one or more files and then use “Attach to shot”.
Rilascia i file su uno shot o direttamente sulla riga di ciak da completare.|||Drop files onto a shot or a take row to complete the pair.
Seleziona una riga ciak e usa ←/→ per scegliere il lato prima di B/R/S.|||Select a take row, then use ←/→ to choose a side before G/R/X.
Nessun file su questo lato.|||No file on this side.
Collegamento eliminato; nessun file originale modificato.|||Attachment removed; no original media changed.
Numero ciak ripristinato alla sequenza automatica di inserimento.|||Take number reset to the automatic insertion sequence.
Seleziona un ciak da rinumerare.|||Select a take to renumber.
Numero ciak|||Take number
Numero per il ciak |||Number for take 
Numero non valido|||Invalid number
Elimina ciak|||Delete take
Eliminare il ciak |||Delete take 
 e le sue associazioni?\nI file originali non saranno toccati.||| and its attachments?\nOriginal media files will not be touched.
Nuovo sotto-shot|||New sub-shot
Nome libero (es. A, B, Dettaglio, Campo largo):|||Custom name (e.g. A, B, Detail, Wide shot):
Nome non valido|||Invalid name
Rinomina sotto-shot|||Rename sub-shot
Nuovo nome per |||New name for 
Rinumera |||Renumber 
Nuovo numero per |||New number for 
Conferma eliminazione|||Confirm deletion
Eliminare |||Delete 
 e le sue associazioni?\nI file originali NON verranno cancellati.||| and its attachments?\nOriginal media files will NOT be deleted.
Convenzione nomi|||Naming convention
Etichetta scena|||Scene label
Etichetta shot|||Shot label
Separatore|||Separator
Cifre minime (0–6)|||Minimum digits (0–6)
Cifre minime: da 0 a 6.|||Minimum digits: 0 to 6.
Valore non valido|||Invalid value
Le etichette non possono essere vuote.|||Labels cannot be empty.
Annulla|||Cancel
Applica|||Apply
Nuovo catalogo creato.|||New catalog created.
Catalogo non salvato|||Unsaved catalog
Vuoi salvare il catalogo prima di continuare?\nSe scegli No e apri/crei un altro catalogo, abbandoni la bozza corrente.|||Save the catalog before continuing?\nChoosing No and opening/creating another catalog will discard your current draft.
Vuoi salvare la bozza con un nome?\n\nSì: scegli un file catalogo.\nNo: la bozza autosalvata sarà recuperata al prossimo avvio.\nAnnulla: resta nel programma.|||Save the draft to a named file?\n\nYes: choose a catalog file.\nNo: the autosaved draft will be recovered next time.\nCancel: stay in the application.
Apri catalogo|||Open catalog
Catalogo SceneSlate|||SceneSlate catalog
Tutti i file|||All files
Apertura non riuscita|||Failed to open
Catalogo aperto: |||Catalog opened: 
Catalogo salvato.|||Catalog saved.
Salvataggio non riuscito|||Save failed
Salva catalogo|||Save catalog
Catalogo JSON|||JSON catalog
Cartella in cui esportare i CSV|||Choose CSV export folder
Esportazione non riuscita|||Export failed
Esportazione completata|||Export completed
Esportati in:\n|||Exported to:\n
 file nel CSV Resolve||| files in Resolve CSV
 avvisi nel report (alcune righe potrebbero essere escluse).||| warnings in the report (some rows may be omitted).
Esportazione completa · |||Export completed · 
 avvisi||| warnings
Nessuna modifica da annullare.|||Nothing to undo.
Ultima modifica annullata.|||Last change undone.
Ultimo catalogo non disponibile: |||Last catalog unavailable: 
Sessione ripristinata: |||Session restored: 
bozza autosalvata|||autosaved draft
Nuovo catalogo|||New catalog
Senza nome|||Untitled
Attenzione: salvataggio automatico non riuscito: |||Warning: autosave failed: 
Impossibile salvare le preferenze di sessione: |||Cannot save session preferences: 
Esporta senza interfaccia|||Export without a GUI
Catalogo da aprire|||Catalog to open
Cartella CSV per --export|||CSV directory for --export
--export richiede --out CARTELLA|||--export requires --out DIRECTORY
Esportati |||Exported 
 file per Resolve; ||| files for Resolve; 
AVVISO:|||WARNING:
File per il nuovo ciak (|||File for new take (
Media |||Media 
File non trovato|||File not found
Impossibile aprire|||Cannot open
Scena già presente.|||Scene already exists.
Shot già presente.|||Shot already exists.
Alcuni file non associati|||Some unpaired files
B · Buona|||G · Good
R · Riserva|||R · Reserve
S · Scarto|||X · Reject
CIAK|||TAKES
 / CIAK||| / TAKES
 ciak · trascina i file su una riga per abbinarli.||| takes · drop files onto a row to pair them.
Il numero deve essere un intero positivo.|||The number must be a positive integer.
Usa numeri naturali maggiori di zero (1, 2, 3...).|||Use positive integers (1, 2, 3...).
La scena |||Scene 
Lo shot |||Shot 
 esiste già.||| already exists.
 non trovata.||| not found.
 non trovato.||| not found.
Seleziona una scena.|||Select a scene.
Il nome del sotto-shot non può essere vuoto.|||Sub-shot name cannot be empty.
Il nome del sotto-shot è troppo lungo (massimo 100 caratteri).|||Sub-shot name is too long (maximum 100 characters).
 già presente nello shot.||| already exists in this shot.
Qualità non valida.|||Invalid rating.
Tipo file non valido.|||Invalid file type.
Seleziona uno shot o sotto-shot.|||Select a shot or sub-shot.
Seleziona uno shot o sotto-shot prima di associare file.|||Select a shot or sub-shot before attaching files.
Ciak di destinazione non trovato.|||Destination take not found.
 già occupato. Usa un nuovo ciak oppure rimuovi il lato.||| is already occupied. Use a new take or unlink that side.
Lato non valido.|||Invalid side.
Versione del catalogo non riconosciuta.|||Unrecognized catalog version.
Catalogo danneggiato: scenes.|||Damaged catalog: scenes.
Convenzione non valida.|||Invalid naming convention.
Padding non valido (0–6).|||Invalid padding (0–6).
Elemento da copiare non trovato.|||Item to copy not found.
Appunti SceneSlate non validi.|||Invalid SceneSlate clipboard.
Descrizione scena non valida.|||Invalid scene description.
Descrizione shot non valida.|||Invalid shot description.
Descrizione sotto-shot non valida.|||Invalid sub-shot description.
Identificatore sotto-shot non valido.|||Invalid sub-shot identifier.
Descrizione/annotazione non valida nel ciak |||Invalid take description/annotation at 
Ciak non trovato.|||Take not found.
Flag ciak manuale non valido.|||Invalid manual take flag.
'''

IT_TO_EN = {}
for line in _PAIRS.splitlines():
    if '|||' in line:
        left,right = line.split('|||',1)
        IT_TO_EN[left.replace('\\n','\n')] = right.replace('\\n','\n')

IT_TO_EN.update({
    '⇄ Collegamenti…': '⇄ Links…',
    'Gestisci collegamenti…': 'Manage links…',
})
IT_TO_EN.update({'Svuota contenuto…':'Clear content…'})
EN_TO_IT = {value: key for key,value in IT_TO_EN.items()}
EN_TO_IT.update({
    'No takes to clear.': 'Nessun ciak da svuotare.',
    'Remove all takes from this item, its descendants and linked equivalents?': 'Rimuovere tutti i ciak da questo elemento, dai suoi discendenti e dagli equivalenti collegati?',
    'Take entries to remove:': 'Ciak da rimuovere:',
    'Structure, node descriptions and link groups are preserved. Original media files are not deleted. Undo is available.': 'Struttura, descrizioni dei nodi e gruppi di collegamento vengono conservati. I file originali non vengono cancellati. È possibile annullare.',
    'Content cleared. Original media unchanged.': 'Contenuto svuotato. File originali invariati.',

    'Sub-shot required': 'Seleziona un sotto-shot',
    'This shot has sub-shots. Select a sub-shot to attach media or add takes.': 'Questo shot contiene sotto-shot. Seleziona un sotto-shot per associare media o aggiungere ciak.',
    'This shot has sub-shots. Paste takes into a sub-shot instead.': 'Questo shot contiene sotto-shot. Incolla i ciak in un sotto-shot.',
    'Linked with:': 'Collegato con:',

    'One-sided (SINGLE)': 'Solo audio/video (SINGLE)',
    'Scene / shot / sub-shot': 'Scena / shot / sotto-shot',
    '✎ Sync editor': '✎ Editor sincronizzazione',
    'Manual synchronization editor': 'Editor sincronizzazione manuale',
    'Compare camera and recorder audio': 'Confronta audio camera e registratore',
    'Camera audio:': 'Audio camera:',
    'External audio:': 'Audio esterno:',
    'Loading waveforms…': 'Caricamento forme d’onda…',
    'Upper: camera audio. Lower: external audio positioned using offset. Drag the lower waveform to adjust alignment.': 'Sopra: audio camera. Sotto: audio esterno spostato secondo l’offset. Trascina la forma d’onda inferiore per regolare l’allineamento.',
    'Position (video):': 'Posizione (video):',
    'Visible interval:': 'Intervallo visibile:',
    'Offset (external source at video zero):': 'Offset (sorgente esterna al tempo video zero):',
    'Nudge:': 'Sposta:',
    'Listen:': 'Ascolto:',
    'Left camera / right recorder': 'Camera a sinistra / registratore a destra',
    'Both mixed': 'Entrambi mixati',
    'Camera only': 'Solo camera',
    'Recorder only': 'Solo registratore',
    '▶ Play 7 s': '▶ Ascolta 7 s',
    '■ Stop': '■ Ferma',
    'Listen for echoes or doubled syllables. A manual OK confirms the current offset, not the whole recording (check drift on long takes).': 'Ascolta eventuali echi o sillabe sdoppiate. L’OK manuale conferma l’offset attuale, non l’intera ripresa (controlla il drift nei ciak lunghi).',
    '✓ Confirm manual alignment': '✓ Conferma sincronizzazione manuale',
    'Reset to suggested offset': 'Ripristina offset suggerito',
    'Waveforms ready. Drag recorder waveform or nudge the offset.': 'Forme d’onda pronte. Trascina il registratore o regola l’offset.',
    'Waveform loading failed:': 'Caricamento forme d’onda fallito:',
    'Playing aligned preview.': 'Riproduzione anteprima allineata.',
    'Preview failed:': 'Anteprima non riuscita:',
    'Enter a finite offset in seconds.': 'Immetti un offset numerico valido in secondi.',
    'Camera': 'Camera',
    'Recorder': 'Registratore',
    'Preparing listening preview…': 'Preparazione anteprima di ascolto…',
    'Confirm manual alignment': 'Conferma sincronizzazione manuale',
    'Save this offset as manually verified? Confirm only after listening to both tracks.': 'Salvare l’offset come verificato manualmente? Conferma solo dopo avere ascoltato entrambe le tracce.',
    'Failed to save alignment': 'Salvataggio dell’allineamento non riuscito',
    'Select a take to edit synchronization.': 'Seleziona un ciak per modificare la sincronizzazione.',
    'Paired media changed while editing; reopen the sync editor.': 'L’abbinamento media è cambiato durante l’editing: riapri l’editor.',
    'Manual synchronization saved. XML export will use the verified offset.': 'Sincronizzazione manuale salvata. L’export XML utilizzerà l’offset verificato.',
    'Replace manual alignment?': 'Sostituire la sincronizzazione manuale?',
    'Automatic synchronization will replace the manually verified offset. Continue?': 'La sincronizzazione automatica sostituirà l’offset verificato manualmente. Continuare?',

    'Unsynced only': 'Solo non sincronizzati',
    'Sync details': 'Dettagli sincronizzazione',
    'Export options': 'Opzioni di esportazione',
    'Choose exports:': 'Seleziona i formati:',
    'CSV metadata and reports': 'Metadati CSV e report',
    'Individual take XML timelines': 'Timeline XML per singolo ciak',
    'Shot XML review timelines': 'Timeline XML per shot',
    'Scene XML review timelines': 'Timeline XML per scena',
    'XML timeline frame rate:': 'Fotogrammi al secondo delle timeline XML:',
    'Waveform sync details': 'Dettagli sincronizzazione audio',
    'Status:': 'Stato:',
    'Offset (audio source at video zero):': 'Offset (audio al tempo video zero):',
    'Method:': 'Metodo:',
    'Note:': 'Note:',
    'Select a take to retry waveform sync.': 'Seleziona un ciak per riprovare la sincronizzazione.',
    'This take needs both video and audio.': 'Il ciak deve avere sia video sia audio.',
    'Waveform synchronization queued.': 'Sincronizzazione in coda.',
    # Optional, explicitly user-approved FFmpeg installation (Windows).
    'Tools ▾': 'Strumenti ▾',
    'FFmpeg setup…': 'Configurazione FFmpeg…',
    'Ask at startup when FFmpeg is missing': 'Chiedi all’avvio se manca FFmpeg',
    'FFmpeg download website': 'Sito download FFmpeg',
    'FFmpeg is ready': 'FFmpeg disponibile',
    'Both required tools are available:': 'Entrambi gli strumenti sono disponibili:',
    'Set up FFmpeg': 'Configura FFmpeg',
    'FFmpeg and ffprobe are missing.': 'FFmpeg e ffprobe non sono disponibili.',
    'SceneSlate can download the Windows essentials build from gyan.dev (linked by ffmpeg.org), verify its published SHA-256 checksum, and install ffmpeg.exe and ffprobe.exe into your user profile. No administrator access or PATH changes are needed. The download is approximately 100–150 MB. No media files will be changed.': 'SceneSlate può scaricare la versione Essentials per Windows da gyan.dev (collegato da ffmpeg.org), verificare il checksum SHA-256 pubblicato e installare ffmpeg.exe e ffprobe.exe nella cartella dell’utente. Non servono privilegi amministrativi né modifiche al PATH. Il download è di circa 100–150 MB. Nessun file video o audio verrà modificato.',
    'Automatic installation is currently supported on Windows. On Linux install FFmpeg using your package manager (for example: sudo apt install ffmpeg) and restart SceneSlate.': 'L’installazione automatica è attualmente disponibile solo su Windows. Su Linux installa FFmpeg dal gestore di pacchetti (per esempio: sudo apt install ffmpeg) e riavvia SceneSlate.',
    'Do not ask again at startup': 'Non chiedermelo più all’avvio',
    'Later': 'Più tardi',
    'Download and install': 'Scarica e installa',
    'Open FFmpeg website': 'Apri il sito di FFmpeg',
    'Installing FFmpeg': 'Installazione di FFmpeg',
    'Connecting to the download server…': 'Connessione al server di download…',
    'Checking the vendor SHA-256 checksum…': 'Lettura del checksum SHA-256 del distributore…',
    'Downloading FFmpeg:': 'Download di FFmpeg:',
    'Verifying and extracting the executables…': 'Verifica ed estrazione degli eseguibili…',
    'Cancelling download…': 'Annullamento del download…',
    'FFmpeg installed': 'FFmpeg installato',
    'FFmpeg and ffprobe are now ready. Previously blocked synchronization attempts will be retried.': 'FFmpeg e ffprobe sono pronti. Le sincronizzazioni bloccate per mancanza degli strumenti verranno riprovate.',
    'FFmpeg installation failed': 'Installazione di FFmpeg non riuscita',

    '⇄ Links…': '⇄ Collegamenti…',
    'Manage links…': 'Gestisci collegamenti…',
    'Link selector': 'Selettore collegamenti',
    'Select linked items': 'Seleziona elementi collegati',
    'Changes to takes and descriptions will be mirrored across all linked items of the same kind.': 'Le modifiche a ciak e descrizioni saranno replicate su tutti gli elementi collegati dello stesso tipo.',
    'Current item:': 'Elemento corrente:',
    'Links updated.': 'Collegamenti aggiornati.',
    'Links removed.': 'Collegamenti rimossi.',
    'Cannot update links': 'Impossibile aggiornare i collegamenti',
    'Apply': 'Applica',
    'Select a scene, shot or sub-shot first.': 'Seleziona prima una scena, uno shot o un sotto-shot.',
})


EN_TO_IT.update({
    'Play selected video (F4)':'Riproduci video selezionato (F4)', 'Video player…':'Lettore video…', 'Use system video player':'Usa lettore video di sistema',
    'Choose video player executable':'Scegli eseguibile del lettore video',
    'Video player:':'Lettore video:', 'System video player selected.':'Lettore video di sistema selezionato.',
    'Select a video to play.':'Seleziona un video da riprodurre.', 'Opening media:':'Apertura file:', 'Unable to open media.':'Impossibile aprire il file.',
    'Media / links':'Media / collegamenti', 'Sub-shot':'Sotto-shot', 'Scene':'Scena',
})


EN_TO_IT.update({
    'Quick sync review':'Revisione rapida sync',
    'Finding shared audio activity…':'Ricerca attività sonora comune…',
    'No significant shared audio found. Open the sync editor.':'Nessuna attività sonora comune significativa. Apri l’editor di sincronizzazione.',
    'Quick review (P)':'Revisione rapida (P)',
    'Confirm synchronization':'Conferma sincronizzazione',
    'Open sync editor':'Apri editor sincronizzazione',
    'Close':'Chiudi',
    'Suggested offset:':'Offset suggerito:',
    'File assignments':'Abbinamenti del file',
    'No overlapping audio to preview.':'Nessuna sovrapposizione audio da ascoltare.',
    'Select video/audio with Left/Right. Select take with Up/Down. Drag files onto a take to pair them.':'Seleziona video/audio con sinistra/destra e il ciak con su/giù. Trascina i file sul ciak per abbinarli.',
    'No assignments':'Nessun abbinamento',
    'Linked group':'Gruppo collegato',
    'Independent assignment':'Abbinamento indipendente',
    'Take actions…':'Azioni ciak…',
    'No suggested offset; open the sync editor.':'Nessun offset suggerito; apri l’editor di sincronizzazione.',
    'Copy the selected node content (Ctrl+C).':'Copia il contenuto selezionato (Ctrl+C).',
    'Paste into the selected node (Ctrl+V).':'Incolla nel nodo selezionato (Ctrl+V).',
    'Select video/audio with Left/Right. Select take with Up/Down.':'Seleziona video/audio con sinistra/destra. Seleziona il ciak con su/giù.',
    'Play proposed alignment immediately; confirm or open the editor (P).':'Ascolta subito l’allineamento proposto; conferma o apri l’editor (P).',
    'Drag files onto a take to pair them.':'Trascina i file su un ciak per abbinarli.',
})

def translate(message, language='en'):
    """Translate application-owned UI strings; do not use on user text or filenames."""
    if not isinstance(message,str):
        return message
    if language == 'it': return EN_TO_IT.get(message,message)
    if language != 'en': return message
    if message in IT_TO_EN: return IT_TO_EN[message]
    # Dynamic status and notification messages are assembled from short fixed
    # fragments. Prefer longest known fragments so their boundaries do not collide.
    result = message
    for original, english in sorted(IT_TO_EN.items(),key=lambda item:-len(item[0])):
        if original and original in result:
            result = result.replace(original,english)
    return result
