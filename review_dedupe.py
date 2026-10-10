"""Deterministic, conservative deduplication of reviews and verified IG slides.

This is a pure helper: no provider calls, cookies, browser state, network,
datastore, console output or secrets. Run ONLY on private user-authorized
source data, never with real quotes in public GitHub Actions fixtures.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

MAX_TEXT = 10000


class ReviewEvidenceError(ValueError):
    """Fixed code only. Never echo an author or quote in an error."""


def normalize(value: str) -> str:
    if not isinstance(value,str) or len(value)>MAX_TEXT:
        raise ReviewEvidenceError("REVIEW_TEXT_INVALID")
    text=value.split("(Translated by Google)",1)[0]
    text=text.casefold().replace("ł","l")
    text=unicodedata.normalize("NFKD",text)
    text="".join(x for x in text if not unicodedata.combining(x))
    text=re.sub(r"[^a-z0-9]+"," ",text)
    return " ".join(text.split())


def _validate_slide(slide: dict) -> bool:
    if not isinstance(slide,dict):
        return False
    if type(slide.get("index")) is not int or not 1<=slide["index"]<=8:
        return False
    if slide.get("verified") is not True:
        return False
    # A source URL alone is not evidence that the actual visual frame was
    # read and its quote transcribed. Never invent one.
    if not isinstance(slide.get("private_image_evidence"),str) or len(
        slide["private_image_evidence"])<12:
        return False
    if not isinstance(slide.get("author"),str) or not isinstance(slide.get("quote"),str):
        return False
    return True


def classify_reviews(reviews: list[dict], slides: list[dict],
                     known_used_ids: set[str], *, expected_slides=8) -> list[dict]:
    """Return only IDs/statuses, no original quotes or author names.

    If ANY of the eight images remains unverified, nothing new can be
    classified as unused. Known-used IDs remain used, but candidates are
    BLOCKED until the whole source has been read.
    """
    if (not isinstance(reviews,list) or not isinstance(slides,list)
        or not isinstance(known_used_ids,set) or expected_slides!=8):
        raise ReviewEvidenceError("REVIEW_INPUT_INVALID")
    ids=[r.get("review_id") for r in reviews if isinstance(r,dict)]
    if (len(ids)!=len(reviews) or len(ids)!=len(set(ids))
        or any(not isinstance(x,str) or not 1<=len(x)<=150 for x in ids)):
        raise ReviewEvidenceError("REVIEW_IDS_INVALID")

    validated=(len(slides)==8 and all(_validate_slide(s) for s in slides)
               and {s["index"] for s in slides}==set(range(1,9)))
    parsed=[]
    if validated:
        for slide in slides:
            author=normalize(slide["author"])
            quote=normalize(slide["quote"])
            parsed.append((slide["index"],author,quote))
    results=[]
    for review in reviews:
        rid=review["review_id"]
        if rid in known_used_ids:
            results.append({"review_id":rid,"status":"used",
                            "matched_slides":[],"reason":"previously_used"})
            continue
        quote=normalize(review.get("quote",""))
        author=normalize(review.get("author",""))
        if not quote:
            results.append({"review_id":rid,"status":"no_text",
                            "matched_slides":[],"reason":"star_rating_only"})
            continue
        if not validated:
            results.append({"review_id":rid,"status":"blocked_incomplete_highlight",
                            "matched_slides":[],"reason":"visual_evidence_missing"})
            continue
        strong_matches=[]
        ambiguous=[]
        for index,ig_author,ig_quote in parsed:
            if not ig_quote:
                continue
            same_author=(len(author)>=3 and author==ig_author)
            exact_quote=(quote==ig_quote)
            shorter=min(len(quote),len(ig_quote))
            longer=max(len(quote),len(ig_quote))
            substantially_contained=(shorter>=30 and shorter/longer>=0.55
                                      and (quote in ig_quote or ig_quote in quote))
            similarity=(SequenceMatcher(None,quote,ig_quote).ratio()
                        if shorter>=25 else 0.0)
            if same_author and (exact_quote or substantially_contained):
                strong_matches.append(index)
            elif (exact_quote or substantially_contained or similarity>=0.78
                  or (same_author and similarity>=0.66)):
                # Shortened quote, alias, same text with different author:
                # never silently mark as used OR unused.
                ambiguous.append(index)
        if strong_matches:
            results.append({"review_id":rid,"status":"used",
                            "matched_slides":sorted(strong_matches),
                            "reason":"same_author_and_quote"})
        elif ambiguous:
            results.append({"review_id":rid,"status":"needs_verification",
                            "matched_slides":sorted(ambiguous),
                            "reason":"possible_shortened_or_aliased_quote"})
        else:
            results.append({"review_id":rid,"status":"unused",
                            "matched_slides":[],"reason":"all_sources_verified"})
    return results
