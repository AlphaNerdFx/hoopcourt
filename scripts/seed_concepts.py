#!/usr/bin/env python3
"""Seed the historical concept mapper.

These are analogies for casual mode, not statements of rule. They are kept in
code rather than retrieved from the corpus precisely because they are editorial
comparisons -- the documents do not contain them, so they must never be presented
as if grounded in a citation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.schema import initialize_database  # noqa: E402

CONCEPTS = [
    ("reserve clause", "a franchise tag that never expires",
     "Before 1976 a team held a player's rights indefinitely; when his contract "
     "ended the team could simply renew it on its own terms, so there was no "
     "true free agency.", 1946, 1976),
    ("coin flip", "a two-team draft lottery with 50/50 odds",
     "Until 1985 the first pick was decided by an actual coin toss between the "
     "worst team in each conference, which is why tanking was a coin-flip bet "
     "rather than a probability curve.", 1966, 1984),
    ("territorial pick", "a hometown exemption from the draft",
     "Until 1966 a team could forfeit its first-round pick to claim a player "
     "from within 50 miles of its arena, which is how Philadelphia got Wilt "
     "Chamberlain.", 1949, 1965),
    ("aba merger", "a league acquisition with an expansion-fee twist",
     "In 1976 four ABA teams (Nets, Nuggets, Pacers, Spurs) joined the NBA; the "
     "rest folded, and their players were distributed in a dispersal draft.",
     1976, 1976),
    ("option clause", "a team option, but one-sided and automatic",
     "Older contracts let the team unilaterally extend a player for another "
     "year on the same terms, the mechanism that made the reserve clause bite.",
     1946, 1976),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="nba_legal.db")
    args = ap.parse_args()

    conn = initialize_database(args.db)
    for term, analogy, explanation, start, end in CONCEPTS:
        conn.execute(
            """INSERT INTO historical_concept_mapper
               (archaic_term, modern_analogy, simplified_explanation,
                valid_from_year, valid_to_year)
               VALUES (?,?,?,?,?)
               ON CONFLICT(archaic_term) DO UPDATE SET
                   modern_analogy=excluded.modern_analogy,
                   simplified_explanation=excluded.simplified_explanation,
                   valid_from_year=excluded.valid_from_year,
                   valid_to_year=excluded.valid_to_year""",
            (term, analogy, explanation, start, end),
        )
    conn.commit()
    n = conn.execute("SELECT count(*) FROM historical_concept_mapper").fetchone()[0]
    print(f"seeded {len(CONCEPTS)} concepts ({n} total in {args.db})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
