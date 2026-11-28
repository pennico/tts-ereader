"""LLM text preparation shared by the v0 CLI pipeline and the v1 app (AC-401,
AC-403, AC-405..AC-407, AC-803).

One LLM call per chunk: clean OCR/spelling errors + repunctuate for speech +
tag dialogue speakers with gender. Language-specific prompts exist for
Italian (Saramago's unmarked dialogue is the hard case) and Danish
(Adler-Olsen); other languages fall back to a generic English prompt that
keeps foreign words intact (AC-407).

Extracted verbatim from edge_reader.py (M3); edge_reader.py re-exports these
so the v0 CLIs keep working (AC-801..AC-803).
"""
from __future__ import annotations

import re
import time

PREPARE_PROMPT_IT = """Sei un preparatore di testi per la sintesi vocale (TTS) in italiano.
{book}Lo stile può avere periodi lunghissimi con catene di virgole e dialoghi incorporati nella narrazione senza virgolette (come in Saramago).

Prepara il testo per essere letto ad alta voce in italiano:
1. PULIZIA: correggi gli evidenti errori di OCR e di ortografia (parole fuse o spezzate, lettere scambiate, accenti mancanti), senza cambiare lo stile né le parole di contenuto. Se una parola è corretta ma rara, lasciala com'è.
2. PUNTEGGIATURA PER IL PARLATO: conserva il ritmo fluido dell'autore, ma dove una catena di virgole renderebbe la lettura a scatti, unisci le clausole brevi in un respiro solo, oppure usa un punto dove termina davvero un pensiero completo, così la voce assume contorni intonativi naturali invece di abbassarsi su ogni virgola.
3. DIALOGHI: metti le parole pronunciate da ciascun personaggio su una riga propria, prefissata dal nome del personaggio in maiuscolo, seguito da [f] o [m] e da due punti (per esempio "MADONNA [f]:"). Le clausole di regia ("gli disse", "domandò", "rispose") restano nella narrazione. Mantieni i paragrafi dell'originale: una riga vuota solo dove l'originale va a capo, un solo a capo tra le righe dello stesso paragrafo.
4. Scrivi i numeri in lettere, sviluppa le abbreviazioni ed elimina i riferimenti a note a piè di pagina (come [3]).
5. Rimuovi anche il corpo delle note a piè di pagina quando è incorporato nel flusso del testo: i passaggi che iniziano con un numero seguito da un trattino, per esempio "3 - Narra la leggenda che...". Questi passaggi non devono essere letti ad alta voce.
6. Non aggiungere, togliere o cambiare nessuna parola di contenuto. Restituisci solo il testo preparato, senza commenti né intestazioni.
7. Non usare mai asterischi, sottolineature o marcature markdown di alcun tipo: il testo va letto da una sintesi vocale, che leggerebbe i simboli ad alta voce."""

PREPARE_PROMPT_DA = """Du er en tekstforbereder til talesyntese (TTS) på dansk.
{book}Stilen kan have lange sætninger med kommakæder og dialog, der kan være indarbejdet i fortællingen uden anførselstegn.

Forbered teksten til at blive læst højt på dansk:
1. RENSNING: ret åbenlyse OCR- og stavefejl (sammensmeltede eller delt ord, ombyttede bogstaver, manglende tegn), uden at ændre stilen eller indholdsord. Hvis et ord er korrekt men sjældent, så lad det stå.
2. TEGNSÆTNING FOR HØJTLÆSNING: bevar forfatterens flydende rytme, men hvor en kommakæde gør læsningen hakket, så saml korte ledsætninger i ét åndedrag, eller brug et punktum hvor en tanke virkelig slutter, så stemmen får naturlige intonationskonturer i stedet for at falde på hvert komma.
3. DIALOG: sæt hver persons replik på sin egen linje, foranstillet med personens navn med store bogstaver, efterfulgt af [f] eller [m] og et kolon (for eksempel "MARCUS [m]:"). Regibemærkninger ("sagde han", "spurgte hun", "svarede han") forbliver i fortællingen. Bevar originalens afsnit: en tom linje kun hvor originalen skifter afsnit, et enkelt linjeskift mellem linjerne i samme afsnit.
4. Skriv tal med bogstaver, fold forkortelser ud, og fjern henvisninger til fodnoter (som [3]).
5. Fjern også selve fodnoteteksten når den er indarbejdet i tekstens strøm: passager der begynder med et tal efterfulgt af en tankestreg, for eksempel "3 - Ifølge sagnet...". Disse passager skal ikke læses højt.
6. Tilføj, fjern eller ændr ingen indholdsord. Bevar fremmedord og citater på andre sprog uændret. Returnér kun den forberedte tekst, uden kommentarer eller overskrifter.
7. Brug aldrig asterisker, understregninger eller markdown-formatering i nogen form: teksten læses af en talesyntese, som ville læse symbolerne højt."""

PREPARE_PROMPT_EN = """You are a text preparer for text-to-speech (TTS).
{book}Prepare the text to be read aloud:
1. CLEANING: fix obvious OCR and spelling errors (fused or split words, swapped letters, missing accents) without changing the style or content words. If a word is correct but rare, leave it as is.
2. PUNCTUATION FOR SPEECH: keep the author's flowing rhythm, but where a chain of commas makes delivery choppy, merge short clauses into one breath, or use a full stop where a thought truly ends.
3. DIALOGUE: put each character's spoken words on their own line, prefixed with the character's name in uppercase, followed by [f] or [m] and a colon (for example "ANNA [f]:"). Stage directions ("he said", "she asked") stay in the narration. Keep the original paragraphs: a blank line only where the original starts a new paragraph, a single line break between lines of the same paragraph.
4. Write numbers as words, expand abbreviations, and drop footnote references (like [3]) and footnote bodies embedded in the text flow.
5. Do not add, remove, or change any content words. Keep foreign words and quotes in other languages unchanged. Return only the prepared text, no comments or headers.
6. Never use asterisks, underscores, or markdown formatting of any kind: the text is read by a speech synthesizer, which would read the symbols aloud."""

PREPARE_PROMPTS = {"it": PREPARE_PROMPT_IT, "da": PREPARE_PROMPT_DA}
DEFAULT_LANGUAGE = "en"

# Danish-specific characters; Italian-specific accented vowels.
_DANISH_CHARS = re.compile(r"[æøåÆØÅ]")
_ITALIAN_CHARS = re.compile(r"[àèéìòùÀÈÉÌÒÙ]")


def normalize_language(language: str | None) -> str:
    """'it-IT' -> 'it'; unknown/None -> the generic English prompt."""
    if not language:
        return DEFAULT_LANGUAGE
    lang = language.strip().split("-")[0].lower()
    return lang if lang in PREPARE_PROMPTS else DEFAULT_LANGUAGE


def detect_language(text: str) -> str:
    """Rough heuristic when a book carries no language metadata."""
    if not text:
        return DEFAULT_LANGUAGE
    if _DANISH_CHARS.search(text):
        return "da"
    if _ITALIAN_CHARS.search(text):
        return "it"
    return DEFAULT_LANGUAGE


# The book line of each prompt (review C221: the Italian prompt named
# "Storia dell'assedio di Lisbona" for every book). Filled from the EPUB's
# metadata; left out when the caller does not know the book.
_BOOK_LINES = {  # (with author, without author)
    "it": ('Il testo è tratto da "{title}" di {author}.\n',
           'Il testo è tratto da "{title}".\n'),
    "da": ('Teksten er trukket fra "{title}" af {author}.\n',
           'Teksten er trukket fra "{title}".\n'),
    "en": ('The text is from "{title}" by {author}.\n',
           'The text is from "{title}".\n'),
}


def _clean_title(title: str) -> str:
    """'Saggio sulla lucidità (Universale economica) (Italian Edition)'
    -> 'Saggio sulla lucidità': store suffixes are noise for the LLM."""
    return re.sub(r"\s*\([^)]*\)", "", title).strip() or title.strip()


def prepare_prompt(language: str | None, book: tuple[str, str] | None = None) -> str:
    """The preparation prompt for a language; book = (title, author)
    adds a line naming the book, None leaves it out."""
    lang = normalize_language(language)
    prompt = PREPARE_PROMPTS.get(lang, PREPARE_PROMPT_EN)
    line = ""
    if book and book[0]:
        author = (book[1] or "").strip()
        known = bool(author) and author.lower() != "unknown"
        template = _BOOK_LINES.get(lang, _BOOK_LINES["en"])[0 if known else 1]
        line = template.replace("{title}", _clean_title(book[0])).replace(
            "{author}", author)
    return prompt.replace("{book}", line)


def chunk_text(text, max_chars=4000):
    """Split text into chunks at paragraph boundaries, each <= max_chars."""
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


# Model preambles seen in practice ("Ecco il testo preparato:",
# "Here is the prepared text:", "Her er teksten:").
_PREAMBLE = re.compile(
    r"^(ecco|here|her er|nedenfor|below|di seguito|testo preparato|"
    r"prepared text|forberedt tekst)\b", re.IGNORECASE)


# Drift check (review C221, finding 3): the LLM must keep the author's
# words. Measured on Saramago (Lucidita, Claude Sonnet, 2 chunks): a
# faithful preparation keeps ~97% of the source words (the rest are
# expanded abbreviations and numbers written out), same word count; a
# chunk cut in half keeps ~48%. One-letter tokens are ignored (initials
# like "p.d.d." are expanded on purpose).
DRIFT_MIN_COVERAGE = 0.90   # share of source words still in the output
DRIFT_RATIO = (0.85, 1.25)  # output words / source words
_WORDS = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


class PrepDrift(ValueError):
    """The prepared text lost or rewrote too much of the source."""


def _word_counts(text):
    from collections import Counter
    return Counter(w.lower() for w in _WORDS.findall(text.replace("’", "'")))


def prep_drift(source, prepared):
    """None when prepared keeps the source's words, else the reason.
    Speaker labels are not counted (they are never spoken)."""
    src = _word_counts(source)
    total = sum(src.values())
    if total < 20:
        return None  # too short to judge
    out = _word_counts(" ".join(t for _s, _g, t in parse_lines(prepared)))
    coverage = sum((src & out).values()) / total
    ratio = sum(out.values()) / total
    if coverage < DRIFT_MIN_COVERAGE:
        return f"kept only {coverage:.0%} of the source words"
    if not DRIFT_RATIO[0] <= ratio <= DRIFT_RATIO[1]:
        return f"word count changed to {ratio:.0%} of the source"
    return None


def llm_prepare(client, model, text, retries=3, language="it", book=None,
                verify=False):
    """One LLM call per chunk: clean + repunctuate + speaker tags.
    book = (title, author) names the book in the prompt. verify=True
    checks the answer against the source (prep_drift), retries a
    drifting answer and raises PrepDrift when the last one drifts too."""
    prompt = prepare_prompt(language, book)
    for attempt in range(retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[{"role": "user", "content": prompt + "\n\n---\n\n" + text}],
            )
            content = response.choices[0].message.content.strip()
            # Guard against markdown fences or preambles
            if content.startswith("```"):
                content = re.sub(r"^```[a-z]*\n?|\n?```$", "", content).strip()
            # Drop a leading preamble line ("Ecco il testo preparato...:")
            # unless it looks like a speaker tag (all-caps name, [f]/[m])
            lines = content.split("\n")
            first = lines[0].strip()
            # Only a real preamble: narration ending in a colon ("poi
            # disse:") is content and must stay (2026-10-17, seen on Claude).
            if first.endswith(":") and not first.isupper() \
                    and not re.search(r"\[[fm]\]:$", first) \
                    and _PREAMBLE.match(first):
                content = "\n".join(lines[1:]).strip()
            # Drop standalone separator lines ("---")
            content = re.sub(r"(?m)^\s*-{3,}\s*$", "", content).strip()
            # Strip markdown emphasis the model sometimes adds despite the
            # prompt (*parola* -> parola); asterisks are never spoken
            # content in this pipeline and were read aloud by the engines.
            content = re.sub(r"\*+([^*\n]+)\*+", r"\1", content)
            content = content.replace("*", "")
            if verify:
                reason = prep_drift(text, content)
                if reason:
                    raise PrepDrift(reason)
            return content
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  LLM call failed ({e}), retrying in {2 ** attempt}s...")
            time.sleep(2 ** attempt)


# Speaker labels the LLM writes: an upper-case name (accented letters,
# Danish ÆØÅ, apostrophes, hyphens, dots and spaces allowed) and a short
# bracketed gender tag. The tag is matched case-insensitively and any
# 1-3 character content is accepted (review C221: "PRESIDENTE [M]:" or a
# hyphenated name fell through as narration and the label was read aloud).
_NAME = r"[A-ZÀ-ÖØ-Ý'’.\- ]{2,}"
_TAG = r"\[([^\]\n]{1,3})\]"


def _gender(tag):
    g = tag.strip().lower()
    return g if g in ("f", "m") else None


def parse_lines(prepared):
    """Split prepared text into (speaker, gender, text) lines.

    Handles both 'NAME [f]: text' on one line and the two-line format where
    'NAME [f]:' stands alone and the dialogue follows on the next line.
    Speaker labels are voice switches, never spoken.
    """
    lines = []
    pending = None  # (speaker, gender) awaiting its text line
    for raw in prepared.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(rf"^({_NAME}?)\s*{_TAG}:\s*(.+)$", line)
        if m:
            speaker = m.group(1).strip() or "dialogo"
            lines.append((speaker, _gender(m.group(2)), m.group(3).strip()))
            pending = None
            continue
        m = re.match(rf"^({_NAME}?)\s*{_TAG}:$", line)
        if m:
            pending = ((m.group(1).strip() or "dialogo"), _gender(m.group(2)))
            continue
        # Untagged speaker label (no gender) — treat as narration-side dialogue
        m = re.match(rf"^({_NAME}):$", line)
        if m:
            pending = (m.group(1).strip(), None)
            continue
        m = re.match(rf"^({_NAME}):\s*(.+)$", line)
        if m:
            lines.append((m.group(1).strip(), None, m.group(2).strip()))
            pending = None
            continue
        speaker, gender = pending if pending else (None, None)
        lines.append((speaker, gender, line))
        pending = None
    return lines


def split_long_narration(lines, max_chars=300):
    """Split long narration lines at sentence boundaries for finer highlighting."""
    out = []
    for speaker, gender, text in lines:
        if speaker or len(text) <= max_chars:
            out.append((speaker, gender, text))
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        buf = ""
        for sentence in sentences:
            if buf and len(buf) + len(sentence) > max_chars:
                out.append((None, None, buf.strip()))
                buf = sentence
            else:
                buf = (buf + " " + sentence).strip()
        if buf:
            out.append((None, None, buf.strip()))
    return out


def paragraph_ends(prepared, lines):
    """For each line of split_long_narration(parse_lines(prepared)): True
    when it is the last line of its paragraph (blank-line separated block
    of the prepared text). Review C221: parse_lines drops the blank lines,
    so every sentence group used to be read as a paragraph of its own.

    Returns None when the per-paragraph parse does not give exactly the
    same lines (a speaker label alone before a blank line): callers then
    keep the old behaviour rather than guess.
    """
    out, flat = [], []
    for block in re.split(r"\n\s*\n", prepared):
        block_lines = split_long_narration(parse_lines(block))
        flat.extend(block_lines)
        out.extend([False] * (len(block_lines) - 1) + [True] if block_lines else [])
    if [tuple(x) for x in flat] != [tuple(x) for x in lines]:
        return None
    # The LLM also puts blank lines inside a sentence ("Per la verità,"
    # / "aggiunse,", seen on Sonnet 2026-11-26): only a finished sentence
    # before a blank line ends a paragraph.
    return [end and ends_sentence(t) for end, (_s, _g, t) in zip(out, lines)]


_SENTENCE_END = re.compile(r"[.!?…][»”\"')\]]*$")


def ends_sentence(text):
    """True when the line ends a sentence (. ! ? …, maybe a closing quote)."""
    return bool(_SENTENCE_END.search(text.rstrip()))


# Loyal mode (owner decision, 2026-10-09): Saramago's comma-chains and
# unmarked dialogue are the author's voice; the LLM preparation keeps
# every word but rewrites the rhythm (merged clauses, added periods,
# dialogue lifted onto speaker lines). The loyal mode keeps the text
# VERBATIM — the only interventions are deferring the edition's
# embedded footnote bodies to their first available point with a
# recall prefix (owner decision, 2026-10-10, see below), dropping the
# [N] reference markers, and splitting paragraphs so one segment
# stays under the ~400-char recitation-filter threshold: first at the
# author's sentence boundaries, then — for comma-chain authors whose
# "sentences" run for thousands of chars — at the author's own clause
# punctuation (commas, semicolons).
# Footnotes (owner decision, 2026-10-10): the edition embeds each note
# body INLINE in the prose, mid-sentence ("...quali strade 1 - Il
# narratore José Maria de Eça..."), running to the end of its
# paragraph, while the interrupted sentence resumes in the next one —
# so a verbatim read hears the note at a wrong time. Loyal mode now
# identifies each body (a "N -" marker whose N matches a [N] reference
# seen earlier; the (?<!\d) guard keeps dates like "1845 - Parigi"
# from matching), lifts it out of the flow, and re-inserts it at the
# FIRST AVAILABLE POINT — in place if the body already sat on a break,
# else the next natural break: a sentence end or a comma followed by a
# capital (the author's dialogue marker, already a stitch break). Each
# note is prefixed with a recall of the word its reference attached to,
# so the listener knows what it refers to:
# "Nota 1, Eça: Il narratore José Maria de Eça...".
FOOTNOTE_REF = re.compile(r"(\S+)\s*\[(\d+)\]")
FOOTNOTE_REF_BARE = re.compile(r"\s*\[\d+\]")
FOOTNOTE_BODY_MARK = re.compile(r"(?<!\d)(\d+)\s*[-–—]\s+")
NOTE_BREAK = re.compile(r"[.!?](?=\s|$)|[,;:]\s+(?=[A-ZÀ-Ù])")


def _next_break(text, pos, spans):
    """First natural break (sentence end, or comma + capital) at or
    after pos, skipping already-inserted note paragraphs; the end of
    the text if none."""
    while True:
        m = NOTE_BREAK.search(text, pos)
        if m is None:
            return len(text)
        inside = next((e for s, e in spans if s <= m.start() < e), None)
        if inside is None:
            return m.end()
        pos = inside


def _defer_footnotes(text):
    """Lift inline footnote bodies out of the prose flow and re-insert
    each at its first available point, prefixed with a recall of the
    reference's anchor word. A body is identified only when its number
    matches a [N] reference seen in the text (the recall needs the
    anchor word); anything else stays verbatim."""
    anchors = {}

    def _drop_ref(m):
        anchors.setdefault(int(m.group(2)),
                           m.group(1).rstrip(".,;:!?«»\"'"))
        return m.group(1)

    text = FOOTNOTE_REF.sub(_drop_ref, text)
    text = FOOTNOTE_REF_BARE.sub("", text)
    done, spans = set(), []
    while True:
        mark = next(
            (m for m in FOOTNOTE_BODY_MARK.finditer(text)
             if not any(s <= m.start() < e for s, e in spans)
             and int(m.group(1)) in anchors
             and int(m.group(1)) not in done), None)
        if mark is None:
            return text
        n = int(mark.group(1))
        done.add(n)
        para_end = text.find("\n\n", mark.start())
        if para_end == -1:
            para_end = len(text)
        body = text[mark.end():para_end].strip()
        head = text[:mark.start()].rstrip()
        tail = text[para_end:].lstrip("\n")
        text = head + "\n\n" + tail
        # First available point: in place if the body already sat on a
        # break (paragraph start, sentence end, or comma + capital);
        # else the next natural break in the remaining prose.
        if (not head or head.endswith((".", "!", "?"))
                or (head.endswith((",", ";", ":"))
                    and tail.lstrip()[:1].isupper())):
            ip = len(head)
        else:
            ip = _next_break(text, len(head), spans)
        note = f"Nota {n}, {anchors[n]}: {body}"
        before = text[:ip].rstrip()
        new = before + "\n\n" + note + "\n\n" + text[ip:].lstrip()
        delta = len(new) - len(text)
        spans = [(s + delta if s >= ip else s, e + delta if s >= ip else e)
                 for s, e in spans]
        spans.append((len(before) + 2, len(before) + 2 + len(note)))
        text = new

CLAUSE_SPLIT = re.compile(r"(?<=[;,])\s+")


def _clause_pieces(text, max_chars):
    """Pack one over-long sentence into <= max_chars pieces, splitting
    only at the author's own clause punctuation (the comma stays at
    the end of the piece before the split, so the text stays verbatim).
    A punctuation-free run longer than the threshold is hard-split at
    a word boundary — rare, but the copyright threshold is a hard
    owner rule."""
    if len(text) <= max_chars:
        return [text]
    pieces, buf = [], ""
    for clause in CLAUSE_SPLIT.split(text):
        while len(clause) > max_chars:
            cut = clause.rfind(" ", 1, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            pieces.append(clause[:cut].strip())
            clause = clause[cut:].strip()
        if buf and len(buf) + 1 + len(clause) > max_chars:
            pieces.append(buf)
            buf = clause
        else:
            buf = f"{buf} {clause}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def loyal_prepare(text, max_chars=300):
    """Author-loyal preparation: no LLM, no rewriting. Footnote bodies
    are lifted out of the prose flow and deferred to their first
    available point with a recall prefix (owner decision, 2026-10-10).

    Returns prepared-style text (one segment per blank-separated line)
    for the same parse_lines/synthesis path: paragraphs kept intact,
    long ones split at sentence boundaries, and sentences that still
    exceed max_chars (Saramago's comma-chains) split at clause
    boundaries — every piece <= max_chars. Deterministic, so no caching
    is needed (unlike llm_prepare).
    """
    text = _defer_footnotes(text)
    pieces = []
    for _speaker, _gender, line in split_long_narration(
            parse_lines(text), max_chars=max_chars):
        pieces.extend(_clause_pieces(line, max_chars))
    return "\n\n".join(pieces)
