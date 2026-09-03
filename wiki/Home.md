# Hoopcourt

Every NBA rule, as it stood.

An era-aware retrieval engine over NBA governing documents. Ask it about 1975 and
it answers from the rules in force in 1975, not from the 2023 CBA.

## Pages

- [Getting Started](Getting-Started)
- [How Era Isolation Works](How-Era-Isolation-Works)
- [The Pre-1995 Problem](The-Pre-1995-Problem)
- [Adding a Document](Adding-a-Document)
- [Evaluation](Evaluation)
- [Troubleshooting](Troubleshooting)

## The problem in one example

Ask a general assistant about a 1997 trade and it will explain it using 2023
second-apron rules. That is rule bleeding. This project makes it structurally
impossible rather than unlikely: a query resolves to a season, the season
resolves to a set of documents, and the vector search is pre-filtered to those
documents before similarity is computed. Text from another era is never a
candidate.

## Coverage

| Seasons | Source |
| --- | --- |
| 1946-1963 | Curated timeline entries, each cited |
| 1964-1994 | Public-domain court opinions, plus the timeline |
| 1995-2029 | The collective bargaining agreements and constitutions themselves |

No public copy of any NBA CBA before 1995 appears to survive, which is why the
early eras rest on litigation and curated entries. Citations state which.
