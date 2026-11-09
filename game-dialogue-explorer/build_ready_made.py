"""Build ready-made-games.js: games added to the explorer that are not in the corpus.

Each game is built from a dialogue file plus a tag file (ready-made/<name>-tags.csv)
that sets each speaker's gender. Only word counts and statistics are written out,
never the dialogue text. The counting mirrors the explorer's own importer.

Usage:
    python3 build_ready_made.py disco=/path/to/output.json gtav=/path/to/gta-pages/ genshin=/path/to/result.json

Edit a tag file and run this again to change gender tags.
"""
import csv
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PRONOUN_COLS = ["i", "me", "my", "you", "he", "she", "they", "them", "his", "hers", "theirs"]
QUESTION_COLS = ["who", "what", "why", "where", "when", "how"]
# Each marker also counts its Chinese equivalents; keep in step with STYLE_MARKERS in index.html.
STYLE_MARKERS = [
    r"[?？]",
    r"[!！]",
    r"\b(maybe|perhaps|probably|might|i think|i guess|i suppose|sort of|kind of)\b|也许|或许|大概|可能|我觉得|我想|似乎|好像|恐怕",
    r"\b(sorry|apologi[sz]e\w*|apologies|forgive me|my fault)\b|对不起|抱歉|不好意思|恕罪|见谅|失礼|得罪",
    r"\b(please|thank|thanks)\b|请|谢谢|多谢|有劳|劳驾",
    r"\b(really|very|so much|totally|absolutely|extremely)\b|非常|十分|很|太|极其|特别|实在",
    r"\b(damn\w*|hell|shit\w*|bastard\w*|crap|bloody|fuck\w*|dammit|piss\w*)\b|混蛋|该死|他妈|他娘的|畜生|混账|王八|狗东西|贱人",
    r"(^|[.!?\n]\s*)(go|come|look|stop|listen|wait|get|give|tell|leave|take|move|hurry|run)\b|(^|[。！？\n])\s*(快|走|来|看|听|等等|别|住手|站住|滚|闭嘴)",
]
STYLE_RES = [re.compile(p, re.M) for p in STYLE_MARKERS]
TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)*")
CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
# Chinese words counted in the English pronoun and question-word columns.
ZH_WORDS = {"i": ["我", "吾", "俺", "在下"], "you": ["你", "您", "汝"], "he": ["他"], "she": ["她"], "they": ["他们", "她们"],
            "who": ["谁"], "what": ["什么", "何"], "why": ["为什么", "为何"], "where": ["哪里", "哪儿", "何处"],
            "when": ["何时"], "how": ["怎么", "如何", "怎样"]}
ZH_TOKENS = {}


def load_lexicon():
    """Positive, negative and emotion word sets from sentiment-lexicon.js (see build_lexicon.py)."""
    with open(os.path.join(HERE, "sentiment-lexicon.js"), encoding="utf-8") as f:
        raw = f.read()
    d = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    return [set(d["pos"]), set(d["neg"])] + [set(ws) for ws in d["emo"]]


SENT_SETS = load_lexicon()


def sentiment_counts(kw):
    """Words that are positive, negative, then each emotion, in the order of sentiment-lexicon.js."""
    return [sum(n for w, n in kw.items() if w in s) for s in SENT_SETS]


def norm(t):
    return t.lower().replace("’", "'").replace("‘", "'")


def segment_zh(texts):
    """Split Chinese lines into words with Intl.Segmenter (via Node), the same splitter the explorer uses in the browser."""
    todo = [t for t in dict.fromkeys(map(norm, texts)) if t not in ZH_TOKENS and CJK_RE.search(t)]
    if not todo:
        return
    js = ("let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const s=new Intl.Segmenter('zh',{granularity:'word'});"
          "process.stdout.write(JSON.stringify(JSON.parse(d).map(t=>[...s.segment(t)].filter(x=>x.isWordLike).map(x=>x.segment))))})")
    out = subprocess.run(["node", "-e", js], input=json.dumps(todo), capture_output=True, text=True, check=True).stdout
    ZH_TOKENS.update(zip(todo, json.loads(out)))


def tokenize(t):
    t = norm(t)
    if CJK_RE.search(t):
        if t not in ZH_TOKENS:
            segment_zh([t])
        return ZH_TOKENS[t]
    return TOKEN_RE.findall(t)


def colcount(kw, w):
    return kw.get(w, 0) + sum(kw.get(z, 0) for z in ZH_WORDS.get(w, []))


def syllables(w):
    if CJK_RE.search(w):
        return len(CJK_RE.findall(w))  # one syllable per character
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    m = re.findall(r"[aeiouy]{1,2}", w)
    return len(m) if m else 1


def strip(t):
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t).replace("*", "")
    return re.sub(r"\s+", " ", t).strip()


def read_tags(name):
    tags = {}
    with open(os.path.join(HERE, "ready-made", name + "-tags.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            tags[r["speaker"]] = r
    return tags


def build_record(game_id, meta, lines, tags, talk=True):
    # Who talks to whom: one exchange per change of speaker; (None, "") marks a break between conversations.
    pairs, prev = {}, None
    for spk, text in lines:
        if spk is None:
            prev = None
            continue
        if not text or not tokenize(text):
            continue
        if prev and prev != spk:
            k = tuple(sorted((prev, spk)))
            pairs[k] = pairs.get(k, 0) + 1
        prev = spk
    acc = {}
    for spk, text in lines:
        if spk is None or not text:
            continue
        a = acc.setdefault(spk, {"lines": 0, "words": 0, "sent": 0, "syl": 0, "kw": {}, "text": []})
        toks = tokenize(text)
        if not toks:
            continue
        a["lines"] += 1
        a["words"] += len(toks)
        a["sent"] += max(1, len(re.findall(r"[.!?]+(?=\s|$)|[。！？]+", text)))
        a["syl"] += sum(syllables(w) for w in toks)
        for w in toks:
            a["kw"][w] = a["kw"].get(w, 0) + 1
        a["text"].append(text.lower())

    chars = []
    for n, a in acc.items():
        if not a["words"]:
            continue
        tag = tags.get(n, {})
        gender = tag.get("gender") or "Other"
        group = tag.get("group") or ("" if tag else "not coded")
        text = "\n".join(a["text"])
        kw = {w: k for w, k in a["kw"].items() if k >= 2 or a["words"] < 400}
        kw = dict(sorted(kw.items(), key=lambda x: -x[1])[:4000])
        chars.append({
            "n": n, "g": gender, "grp": [group] if group else [],
            "s": [a["lines"], a["words"], a["sent"], a["syl"]],
            "pr": [colcount(a["kw"], w) for w in PRONOUN_COLS],
            "qw": [colcount(a["kw"], w) for w in QUESTION_COLS],
            "st": [len(r.findall(text)) for r in STYLE_RES],
            # English word lists, so Chinese scripts get no sentiment.
            **({} if meta.get("lang") == "zh" else {"se": sentiment_counts(a["kw"])}),
            "kw": kw,
        })
    chars.sort(key=lambda c: -c["s"][1])
    pcs = [n for n, t in tags.items() if (t.get("player_character") or "").lower() == "yes"]
    rec = dict(meta, id=game_id, pcs=pcs, groups={}, chars=chars)
    if talk:
        kept = {c["n"] for c in chars}
        rec["talk"] = [[a, b, n] for (a, b), n in sorted(pairs.items(), key=lambda x: -x[1]) if n >= 2 and a in kept and b in kept][:3000]
    return rec


def disco_elysium(path):
    """Disco Elysium conversations export: {"conversations": [[{"actor", "dialogue"}, ...], ...]}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lines = []
    for conv in data["conversations"]:
        lines.append((None, ""))
        for row in conv:
            text = row.get("dialogue", "")
            if text.startswith("["):
                continue  # game-logic checks such as [Action/Check: ...]
            # NPC lines mix speech in quotes with narration; keep only the spoken part.
            quoted = re.findall(r"\"([^\"]+)\"", text)
            if quoted:
                text = " ".join(quoted)
            lines.append((row["actor"], strip(text)))
    meta = {
        "title": "Disco Elysium",
        "series": "Disco Elysium",
        "year": 2019,
        "source": "https://huggingface.co/datasets/allura-org/disco-elysium-conversations-raw",
        "sourceType": "game data",
        "completeness": "partial",
        "choices": "partial",
        "custom": {
            "where": "ready",
            "notes": "About 1,700 conversations (roughly 200,000 words) from a community export of the game's files. "
                     "Narration outside quotation marks was removed from character lines. The skills are the player "
                     "character's inner voices and are tagged Neutral; objects, documents and minor speakers are untagged (Other).",
            "rights": "Dialogue by ZA/UM. Only word counts are stored here.",
            "importOpts": {"format": "json"},
        },
        "scriptUrl": "https://huggingface.co/datasets/allura-org/disco-elysium-conversations-raw/resolve/main/output.json",
        "scriptMB": 3.4,
    }
    return build_record("extra/DiscoElysium", meta, lines, read_tags("disco-elysium"))


def speaker_name(s):
    """Drop notes such as "(text message)" or "In Spanish" from a transcript's speaker label."""
    s = html.unescape(html.unescape(s)).replace(":", " ")
    s = re.sub(r"\([^)]*\)|\bIn (Spanish|German|French|Italian|Polish|Russian|Hungarian)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Spelling variants on Grand Theft Wiki. Michael and Amanda go by Townley in the prologue.
GTA_ALIASES = {
    "Lamar Davies": "Lamar Davis", "Lamar Davisp": "Lamar Davis", "Lamar Daivs": "Lamar Davis",
    "Ron Jakowksi": "Ron Jakowski", "Ron Jakowsi": "Ron Jakowski", "Sssquatch": "Sasquatch",
    "Michael Townley": "Michael De Santa", "Michael Tonwley": "Michael De Santa", "Amanda Townley": "Amanda De Santa",
    "Police officer": "Police Officer",
}


def gta_v(folder):
    """Grand Theft Wiki mission script pages (saved .html), where each line is <p><b>Speaker</b>: text</p>."""
    lines, pages = [], 0
    for name in sorted(os.listdir(folder)):
        lines.append((None, ""))
        if not name.endswith(".html"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            page = f.read()
        body = page[page.find("mw-parser-output"):]
        body = body[:body.find("printfooter")]
        pages += 1
        for para in re.findall(r"<p>(.*?)</p>", body, re.S):
            m = re.match(r"\s*<b>([^<]{1,80})</b>\s*(?:\([^)]*\))?\s*:(.*)$", para, re.S)
            if not m:
                continue
            spk = speaker_name(m.group(1))
            text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
            if spk:
                lines.append((GTA_ALIASES.get(spk, spk), strip(text)))
    meta = {
        "title": "Grand Theft Auto V",
        "series": "Grand Theft Auto",
        "year": 2013,
        "source": "https://www.grandtheftwiki.com/Category:Scripts_for_GTA_V",
        "sourceType": "fan wiki transcripts",
        "completeness": "partial",
        "choices": "no",
        "custom": {
            "where": "ready",
            "notes": f"The {pages} mission scripts transcribed on Grand Theft Wiki: mostly side missions (Strangers and Freaks, "
                     "Paparazzo, Epsilon, Tonya, rampages) plus a few story missions, so the main story is under-represented. "
                     "Stage directions in brackets were removed. Unnamed and one-off speakers are untagged (Other).",
            "rights": "Dialogue by Rockstar Games; transcripts by Grand Theft Wiki contributors. Only word counts are stored here.",
            "importOpts": {"format": "auto"},
            "speakerMap": {k.lower(): v for k, v in GTA_ALIASES.items()},
        },
        "scriptHow": "many-pages",
    }
    return build_record("extra/GTAV", meta, lines, read_tags("gta-v"))


def genshin_impact(path):
    """genshin-voice result.json: {id: {"language", "speaker", "transcription", ...}}, one entry per voiced line."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lines = []
    for row in data.values():
        spk, text = (row.get("speaker") or "").strip(), row.get("transcription") or ""
        if row.get("language") != "English(US)" or not spk or spk.startswith("#") or not text:
            continue
        text = re.sub(r"<[^>]+>|\{[^}]*\}|#", " ", text)  # color tags and name placeholders
        lines.append((spk, strip(text)))
    meta = {
        "title": "Genshin Impact",
        "series": "Genshin Impact",
        "year": 2020,
        "source": "https://huggingface.co/datasets/simon3000/genshin-voice",
        "sourceType": "voice-line data",
        "completeness": "voiced lines only",
        "choices": "no",
        "custom": {
            "where": "ready",
            "notes": "Every English voiced line in the game up to mid-2026 (story, quests, events, character voice-overs and "
                     "combat lines), from a community dataset. Unvoiced text is missing, including most of the Traveler's "
                     "dialogue choices, so the Traveler looks quieter than in play. Hero (Aether) and Heroine (Lumine) are "
                     "the two versions of the Traveler and mostly say the same lines. Minor speakers are untagged (Other).",
            "rights": "Dialogue by HoYoverse. Only word counts are stored here.",
            "importOpts": {"format": "json"},
        },
    }
    # Voice lines are listed by audio file, not by conversation, so their order says nothing about who talks to whom.
    return build_record("extra/GenshinImpact", dict(meta, scriptHow="too-big"), lines, read_tags("genshin-impact"), talk=False)


def rdr2(path):
    """Game Scripts Wiki full transcript (saved .html), where each line is <b>Speaker:</b> text<br />."""
    with open(path, encoding="utf-8") as f:
        page = f.read()
    lines = []
    for seg in re.split(r"<br\s*/?>", page):
        m = re.match(r"\s*<b>([^<]{1,60}?):?\s*</b>\s*:?(.*)$", seg, re.S)
        if not m:
            continue
        spk = speaker_name(m.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        if spk and len(spk.split()) <= 5:
            lines.append((spk, strip(text)))
    meta = {
        "title": "Red Dead Redemption 2",
        "series": "Red Dead Redemption",
        "year": 2018,
        "source": "https://game-scripts-wiki.blogspot.com/2022/01/red-dead-redemption-2.html",
        "sourceType": "fan transcript",
        "completeness": "main story",
        "choices": "no",
        "custom": {
            "where": "ready",
            "notes": "A fan transcript of the story missions, prologue to epilogue, from Game Scripts Wiki. Side content, "
                     "camp chatter and most ambient lines are missing. Stage directions in brackets were removed. "
                     "Unnamed and one-off speakers are untagged (Other).",
            "rights": "Dialogue by Rockstar Games; transcript by Game Scripts Wiki. Only word counts are stored here.",
            "importOpts": {"format": "auto"},
        },
        "scriptHow": "save-page",
    }
    return build_record("extra/RDR2", meta, lines, read_tags("rdr2"))


CP77_ALIASES = {"Takamura": "Takemura", "Takemira": "Takemura", "Talkemuro": "Takemura", "Tokemu": "Takemura",
                "Alt Cunningham": "Alt", "AIt Cunningham": "Alt", "Cunningham": "Alt", "Jarkie": "Jackie", "JackIe": "Jackie",
                "Mama Weles": "Mamá Welles", "Conch Fred": "Coach Fred", "Cooch Fred": "Coach Fred",
                "Milt Nouman": "Milt Nauman", "Mil Nauman": "Milt Nauman", "Mit Nauman": "Milt Nauman",
                "Snider Murphy": "Spider Murphy", "T-Bud": "T-Bug", "Caselus Ryder": "Cassius Ryder",
                "Stinis": "Stints", "Sunts": "Stints", "Roxonne": "Roxanne", "Honoko": "Hanako", "Harako": "Hanako",
                "Johnne": "Johnny", "Karry": "Kerry", "Victor": "Viktor", "Panama": "Panam", "Clatre": "Claire",
                "Grouple": "Groupie", "Net Watch Agent": "NetWatch Agent", "NCPD officer": "NCPD Officer",
                "Tyger Claws Boss": "Tyger Claw Boss"}


def cyberpunk_2077(path):
    """Game Scripts Wiki full transcript (saved .html): <font color=..><b>Speaker:</b></font> text<br />."""
    with open(path, encoding="utf-8") as f:
        page = f.read()
    start = page.find("entry-content")
    body = re.sub(r"</?font[^>]*>", "", page[start:page.find("post-footer", start)])
    lines = []
    for seg in re.split(r"<br\s*/?>", body):
        m = re.match(r"\s*<b>([^<]{1,60}?):?\s*</b>\s*:?(.*)$", seg, re.S)
        if not m:
            continue
        spk = speaker_name(m.group(1))
        spk = CP77_ALIASES.get(spk, spk)
        text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        if spk and len(spk.split()) <= 5 and not spk.startswith("["):
            lines.append((spk, strip(text)))
    meta = {
        "title": "Cyberpunk 2077",
        "series": "Cyberpunk",
        "year": 2020,
        "source": "https://game-scripts-wiki.blogspot.com/2020/12/cyberpunk-2077-full-transcript.html",
        "sourceType": "fan transcript",
        "completeness": "main story",
        "choices": "yes",
        "custom": {
            "where": "ready",
            "notes": "A fan transcript of one playthrough of the main story (base game, no Phantom Liberty), from Game Scripts Wiki. "
                     "Most side jobs, gigs and ambient lines are missing, and other dialogue choices would change V's lines. "
                     "V's gender is chosen by the player (this playthrough's V is not identified), so V is tagged Neutral. "
                     "Misspelled speaker names were merged. Unnamed and one-off speakers are untagged (Other).",
            "rights": "Dialogue by CD PROJEKT RED; transcript by Game Scripts Wiki. Only word counts are stored here.",
            "importOpts": {"format": "auto"},
            "speakerMap": {k.lower(): v for k, v in CP77_ALIASES.items()},
        },
        "scriptHow": "save-page",
    }
    return build_record("extra/Cyberpunk2077", meta, lines, read_tags("cyberpunk-2077"))


def wiki_templates(text, name):
    """Bodies of every {{name|...}} template in wikitext, with nested templates left inside."""
    out, i, key = [], 0, "{{" + name + "|"
    while (i := text.find(key, i)) >= 0:
        j, depth = i + 2, 1
        while j < len(text) and depth:
            if text.startswith("{{", j):
                depth, j = depth + 1, j + 2
            elif text.startswith("}}", j):
                depth, j = depth - 1, j + 2
            else:
                j += 1
        out.append(text[i + len(key):j - 2])
        i = j
    return out


def wiki_params(body):
    """Split a template body on its top-level | characters."""
    parts, depth, cur = [], 0, ""
    for k, ch in enumerate(body):
        if body.startswith("{{", k) or body.startswith("[[", k):
            depth += 1
        elif body.startswith("}}", k) or body.startswith("]]", k):
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def wiki_plain(t):
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    prev = None
    while prev != t:
        prev = t
        # {{称呼差分|x}} is how NPCs address the player; the wiki gives the male-player form, or nothing.
        t = re.sub(r"\{\{([^{}|]+)(?:\|([^{}]*))?\}\}",
                   lambda m: (m.group(2) or "").split("|")[0] if m.group(2) else ("少侠" if m.group(1).strip() == "称呼差分" else ""), t)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t).replace("'''", "").replace("''", "")
    return strip(t)


WWM_UNKNOWN = {"？", "？？？", "?", "???", "说话人待核"}
# Gender carried by a title or kinship term at the end (or start) of a speaker's name.
WWM_TITLE_GENDER = [
    ("Female", ("少女", "姑娘", "娘子", "夫人", "小姐", "媳妇", "奶奶", "婆婆", "姐姐", "妹妹", "丫头", "婶", "婆", "姑", "娘", "姐", "妹", "嫂", "妈", "姨", "妃", "女"), ("女",)),
    ("Male", ("公子", "少爷", "老爷", "和尚", "小子", "大叔", "老头", "大哥", "哥", "兄", "弟", "叔", "伯", "爷", "爹", "汉", "郎", "公", "翁"), ("男",)),
]


def where_winds_meet(path):
    """燕云十六声 Huiji wiki archive (pages.json from anonymous99-Rise/yanyun-guide): {{对话|speaker|line}} templates."""
    with open(path, encoding="utf-8") as f:
        pages = json.load(f)["pages"]
    lines, wiki_gender = [], {}
    for p in pages:
        w = p.get("wikitext") or ""
        m = re.search(r"\|\s*性别\s*=\s*([男女公母])", w)
        if m:
            wiki_gender[p["title"]] = m.group(1)
        lines.append((None, ""))
        for body in wiki_templates(w, "对话"):
            parts = wiki_params(body)
            if len(parts) < 2:
                continue
            spk, text = wiki_plain(parts[0]), wiki_plain(parts[1])
            if not spk or not text:
                continue
            lines.append(("Unknown speaker" if spk in WWM_UNKNOWN else spk, text))
    segment_zh([t for _, t in lines])

    # Tags: start from ready-made/where-winds-meet-tags.csv (hand edits win), then fill gaps from the wiki.
    tag_path = os.path.join(HERE, "ready-made", "where-winds-meet-tags.csv")
    tags = read_tags("where-winds-meet") if os.path.exists(tag_path) else {}
    counts = {}
    for spk, _ in lines:
        if spk is not None:
            counts[spk] = counts.get(spk, 0) + 1
    for spk, n in sorted(counts.items(), key=lambda x: -x[1]):
        if spk in tags:
            continue
        row = {"speaker": spk, "gender": "", "player_character": "", "group": ""}
        if spk == "少东家":
            row.update(gender="Neutral", player_character="yes", group="player character (gender chosen by player)")
        elif spk in wiki_gender:
            g = wiki_gender[spk]
            row.update(gender={"男": "Male", "女": "Female", "公": "Male", "母": "Female"}[g],
                       group="gender from wiki character page" + (" (animal)" if g in "公母" else ""))
        else:
            for gender, ends, starts in WWM_TITLE_GENDER:
                hit = next((e for e in ends if spk.endswith(e)), None) or next((s for s in starts if spk.startswith(s)), None)
                if hit:
                    row.update(gender=gender, group=f"gender from title in name ({hit or spk})")
                    break
        if row["gender"] or n >= 30:
            tags[spk] = row  # untagged speakers with 30+ lines are listed so they can be filled in by hand
    with open(tag_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["speaker", "gender", "player_character", "group"])
        wr.writeheader()
        for spk in sorted(tags, key=lambda s: -counts.get(s, 0)):
            wr.writerow({k: tags[spk].get(k, "") for k in wr.fieldnames})
    tags = {k: v for k, v in tags.items() if v.get("gender")}

    meta = {
        "title": "Where Winds Meet (燕云十六声)",
        "series": "Where Winds Meet",
        "year": 2024,
        "source": "https://raw.githubusercontent.com/anonymous99-Rise/yanyun-guide/main/content/huiji/pages.json",
        "sourceType": "fan wiki transcript",
        "completeness": "partial",
        "choices": "partial",
        "lang": "zh",
        "custom": {
            "where": "ready",
            "notes": "Chinese text. Quest dialogue transcribed by players on the 燕云十六声 Huiji wiki (yy16s.huijiwiki.com), "
                     "from a GitHub archive of the wiki made in October 2026. Words are split with the browser's Chinese word "
                     "splitter, so counts are of words, not characters, and \"syllables per word\" means characters per word. "
                     "The player character 少东家 is tagged Neutral. Other genders come from the wiki's character pages or from a "
                     "title in the speaker's name (婶 aunt, 大哥 elder brother, 姑娘 young woman); everyone else is untagged (Other). "
                     "Where NPCs address the player differently by the player's gender, the wiki gives the male-player form "
                     "(师弟, 大哥哥, 郎君). Conversations with the AI-chat NPCs are not scripted and are not included.",
            "rights": "Dialogue by Everstone Studio / NetEase. Transcriptions from the 燕云十六声 Huiji wiki (CC BY-NC-SA). Only word counts are stored here.",
            "importOpts": {"format": "json"},
        },
        "scriptUrl": "https://raw.githubusercontent.com/anonymous99-Rise/yanyun-guide/main/content/huiji/pages.json",
        "scriptMB": 13.5,
    }
    return build_record("extra/WhereWindsMeet", meta, lines, tags)


BUILDERS = {"disco": disco_elysium, "gtav": gta_v, "genshin": genshin_impact, "rdr2": rdr2, "cp77": cyberpunk_2077, "wwm": where_winds_meet}


def main(args):
    sources = dict(a.split("=", 1) for a in args)
    out_path = os.path.join(HERE, "ready-made-games.js")
    games = []
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            raw = f.read()
        games = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    for key, path in sources.items():
        rec = BUILDERS[key](path)
        games = [g for g in games if g["id"] != rec["id"]] + [rec]
        coded = sum(c["s"][1] for c in rec["chars"] if c["g"] != "Other")
        total = sum(c["s"][1] for c in rec["chars"])
        print(f"{rec['title']}: {len(rec['chars'])} speakers, {total} words, {coded / total:.0%} of words gender-tagged")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("window.READY_MADE = ")
        json.dump(games, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print("Wrote", out_path)


if __name__ == "__main__":
    main(sys.argv[1:])
