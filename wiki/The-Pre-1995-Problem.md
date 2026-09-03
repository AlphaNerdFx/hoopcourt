# The Pre-1995 Problem

The corpus originally covered 1995 to 2029. Everything earlier, 49 seasons from
the league's founding, was empty, and all four historical trigger terms pointed
into that void. The routing was correct and the answer was correctly nothing.

## What is actually available

No public copy of any NBA collective bargaining agreement before 1995 appears to
exist. The most complete public archive was enumerated through the GitHub API and
holds seven files, the earliest from 1995. Archive.org's NBA results are team
media guides being resold. Law review articles discuss the 1988 agreement without
reproducing it.

Two source classes do exist, are free, and are legally clean.

Court opinions are public domain and complete. The reserve clause, the draft, the
four-year eligibility rule and the first salary cap were all litigated, and the
opinions state what the rules were:

| Case | Covers |
| --- | --- |
| Haywood v. NBA (1971) | four-year eligibility rule |
| Denver Rockets v. All-Pro (1971) | the same rule, struck as a group boycott |
| Robertson v. NBA (1975) | reserve clause, draft, ABA merger |
| Robertson v. NBA (1977) | the settlement that ended the reserve clause |
| Wood v. NBA (1987) | 1983 salary cap and draft upheld |
| Bridgeman v. NBA (1987) | cap and right of first refusal |
| NBA v. Williams (1995) | terms surviving CBA expiration |

Text comes from the Caselaw Access Project, which is static, open and
unauthenticated. CourtListener is better for finding a case but its full-text API
requires a key and its pages sit behind a bot challenge.

A curated timeline carries what the litigation does not reach, such as
territorial picks and the coin flip. `CLAUDE.md` named this mechanism from the
start and it had never been built.

## Source tiers

Because these sources are weaker than a governing document, every document
declares what its citations are worth.

| Tier | Meaning | Renders as |
| --- | --- | --- |
| `primary` | the governing document | `2023 NBA CBA, Article II, Section 7, p. 37` |
| `judicial` | a court opinion describing the rule | `Robertson v. NBA (S.D.N.Y. 1975), part 18 [court opinion]` |
| `timeline` | a curated, cited entry | `Reserve clause (1946-1976) [curated timeline entry]` |

Without this, a hand-written summary rendered in the governing-document shape
would look identical to the rule itself.

## Two channels, not one ranking

Timeline summaries are dense and query-shaped, so they would outrank primary text
if they competed for the same slots. They are retrieved separately:

- `sources` answers what the rule was, from primary and judicial tiers.
- `timeline` answers when it changed.

A vector search always returns its nearest rows however far away they are, so the
timeline channel also applies a distance threshold. Measured over relevant and
irrelevant queries the separation was clean: 0.240 to 0.338 when an entry
genuinely answers, 0.457 to 0.621 when nothing does. The cutoff sits at 0.40.
Without it, "what were the luxury tax rules in 1952?" returned the reserve-clause
entry simply because it was closest.
