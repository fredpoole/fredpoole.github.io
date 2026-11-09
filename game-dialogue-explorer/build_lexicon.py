"""Build sentiment-lexicon.js: the word lists the explorer uses for sentiment and emotion.

Positive and negative words come from the VADER lexicon (Hutto & Gilbert, 2014; MIT licence):
a word is positive if its average rating is above 0 and negative if below 0. Only single words
are kept, since the explorer counts words one at a time.

Emotion words come from emotion-words.csv, the explorer's own short list of everyday spoken words
for the eight emotions in Plutchik's wheel. Edit that file and run this again to change it.

Usage:
    python3 build_lexicon.py /path/to/vader_lexicon.txt

Source:
    https://github.com/cjhutto/vaderSentiment/blob/master/vaderSentiment/vader_lexicon.txt
"""
import csv
import json
import os
import re
import sys

EMOTIONS = ["joy", "trust", "anticipation", "surprise", "fear", "sadness", "anger", "disgust"]
WORD = re.compile(r"^[a-z][a-z']*$")


def main(vader_path):
    pos, neg = [], []
    with open(vader_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or not WORD.match(parts[0]):
                continue
            score = float(parts[1])
            if score > 0:
                pos.append(parts[0])
            elif score < 0:
                neg.append(parts[0])
    here = os.path.dirname(os.path.abspath(__file__))
    emo = {e: set() for e in EMOTIONS}
    with open(os.path.join(here, "emotion-words.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            emo[r["emotion"].strip()].add(r["word"].strip().lower())
    emo = {e: sorted(ws) for e, ws in emo.items()}
    data = {"pos": sorted(pos), "neg": sorted(neg), "emotions": EMOTIONS, "emo": [emo[e] for e in EMOTIONS]}
    out = os.path.join(here, "sentiment-lexicon.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("// Positive/negative words: VADER (Hutto & Gilbert 2014, MIT licence). Emotion words: emotion-words.csv (this tool's own list).\n")
        f.write("window.SENTIMENT = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";\n")
    print(f"{len(pos)} positive, {len(neg)} negative, " + ", ".join(f"{e} {len(emo[e])}" for e in EMOTIONS))
    print("Wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
