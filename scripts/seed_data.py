"""Seed vendors and gold questions into the database.

Usage:
    uv run python scripts/seed_data.py

What this does:
    1. Upserts the 3 vendor rows (Tavily, Exa, Serper) with budget info.
    2. Creates a GoldSet v1 (status=draft) if it doesn't exist.
    3. Inserts 50 gold questions into the gold set.

This script is idempotent: running it again updates existing vendors
and skips if the gold set already has 50 questions.
"""

import asyncio

from searchdrift.api.app import app, lifespan
from searchdrift.models import GoldSet, Question, Vendor
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

VENDORS = [
    {
        "id": "tavily",
        "enabled": True,
        "budget_calls": 1000,
        "budget_period": "monthly",
    },
    {
        "id": "exa",
        "enabled": True,
        "budget_calls": 2500,
        "budget_period": "total",
    },
    {
        "id": "serper",
        "enabled": True,
        "budget_calls": 2500,
        "budget_period": "total",
    },
]

# ---------------------------------------------------------------------------
# 50 Gold Questions
# ---------------------------------------------------------------------------
# Split: 25 entity + 25 URL
# Difficulty: ~35 easy + ~15 medium
# Topics: tech, history, science, geography, business, sports/culture, misc

QUESTIONS = [
    # === ENTITY QUESTIONS (25) ===
    # --- Tech / Programming (5) ---
    {
        "key": "python-creator",
        "text": "Who created the Python programming language?",
        "scoring_unit": "entities",
        "gold": [{"name": "Guido van Rossum", "aliases": ["Guido"]}],
        "verification": "manual",
    },
    {
        "key": "linux-creator",
        "text": "Who created the Linux operating system?",
        "scoring_unit": "entities",
        "gold": [{"name": "Linus Torvalds", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "javascript-creator",
        "text": "Who created the JavaScript programming language?",
        "scoring_unit": "entities",
        "gold": [{"name": "Brendan Eich", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "typescript-creator",
        "text": "Who created TypeScript?",
        "scoring_unit": "entities",
        "gold": [{"name": "Anders Hejlsberg", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "git-creator",
        "text": "Who created the Git version control system?",
        "scoring_unit": "entities",
        "gold": [{"name": "Linus Torvalds", "aliases": []}],
        "verification": "manual",
    },
    # --- History (4) ---
    {
        "key": "titanic-year",
        "text": "What year did the RMS Titanic sink?",
        "scoring_unit": "entities",
        "gold": [{"name": "1912", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "first-moon-landing",
        "text": "Who was the first person to walk on the Moon?",
        "scoring_unit": "entities",
        "gold": [{"name": "Neil Armstrong", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "berlin-wall-fall",
        "text": "What year did the Berlin Wall fall?",
        "scoring_unit": "entities",
        "gold": [{"name": "1989", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "ww2-end-year",
        "text": "What year did World War II end?",
        "scoring_unit": "entities",
        "gold": [{"name": "1945", "aliases": []}],
        "verification": "manual",
    },
    # --- Science (5) ---
    {
        "key": "photosynthesis-gas",
        "text": "What gas do plants produce during photosynthesis?",
        "scoring_unit": "entities",
        "gold": [{"name": "oxygen", "aliases": ["O2"]}],
        "verification": "manual",
    },
    {
        "key": "speed-of-light",
        "text": "What is the speed of light in vacuum?",
        "scoring_unit": "entities",
        "gold": [
            {
                "name": "299792458 metres per second",
                "aliases": ["300000 km/s", "3x10^8 m/s"],
            }
        ],
        "verification": "manual",
    },
    {
        "key": "water-chemical-formula",
        "text": "What is the chemical formula for water?",
        "scoring_unit": "entities",
        "gold": [{"name": "H2O", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "closest-star",
        "text": "What is the closest star to Earth?",
        "scoring_unit": "entities",
        "gold": [{"name": "the Sun", "aliases": ["Sun", "Sol"]}],
        "verification": "manual",
    },
    {
        "key": "dna-structure-discoverers",
        "text": "Who discovered the structure of DNA?",
        "scoring_unit": "entities",
        "gold": [
            {"name": "James Watson", "aliases": ["Watson"]},
            {"name": "Francis Crick", "aliases": ["Crick"]},
        ],
        "verification": "manual",
    },
    # --- Geography (5) ---
    {
        "key": "capital-australia",
        "text": "What is the capital of Australia?",
        "scoring_unit": "entities",
        "gold": [{"name": "Canberra", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "capital-canada",
        "text": "What is the capital of Canada?",
        "scoring_unit": "entities",
        "gold": [{"name": "Ottawa", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "longest-river",
        "text": "What is the longest river in the world?",
        "scoring_unit": "entities",
        "gold": [{"name": "the Nile", "aliases": ["Nile", "Nile River"]}],
        "verification": "manual",
    },
    {
        "key": "largest-country",
        "text": "What is the largest country in the world by area?",
        "scoring_unit": "entities",
        "gold": [{"name": "Russia", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "mount-everest-country",
        "text": "In which country is Mount Everest located?",
        "scoring_unit": "entities",
        "gold": [{"name": "Nepal", "aliases": []}],
        "verification": "manual",
    },
    # --- Business (3) ---
    {
        "key": "spacex-founder",
        "text": "Who founded SpaceX?",
        "scoring_unit": "entities",
        "gold": [{"name": "Elon Musk", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "amazon-founder",
        "text": "Who founded Amazon?",
        "scoring_unit": "entities",
        "gold": [{"name": "Jeff Bezos", "aliases": []}],
        "verification": "manual",
    },
    {
        "key": "microsoft-founders",
        "text": "Who founded Microsoft?",
        "scoring_unit": "entities",
        "gold": [
            {"name": "Bill Gates", "aliases": ["Gates"]},
            {"name": "Paul Allen", "aliases": ["Allen"]},
        ],
        "verification": "manual",
    },
    # --- Sports / Culture (3) ---
    {
        "key": "messi-sport",
        "text": "What sport does Lionel Messi play?",
        "scoring_unit": "entities",
        "gold": [{"name": "football", "aliases": ["soccer"]}],
        "verification": "manual",
    },
    {
        "key": "harry-potter-author",
        "text": "Who wrote the Harry Potter book series?",
        "scoring_unit": "entities",
        "gold": [{"name": "J.K. Rowling", "aliases": ["Joanne Rowling", "Rowling"]}],
        "verification": "manual",
    },
    {
        "key": "mona-lisa-artist",
        "text": "Who painted the Mona Lisa?",
        "scoring_unit": "entities",
        "gold": [
            {
                "name": "Leonardo da Vinci",
                "aliases": ["da Vinci", "Leonardo"],
            }
        ],
        "verification": "manual",
    },
    # === URL QUESTIONS (25) ===
    # --- Tech / Programming (5) ---
    {
        "key": "mdn-javascript",
        "text": "What is the Mozilla Developer Network page for JavaScript?",
        "scoring_unit": "urls",
        "gold": [
            {"url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript"}
        ],
        "verification": "manual",
    },
    {
        "key": "github-official",
        "text": "What is the GitHub website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://github.com/"}],
        "verification": "manual",
    },
    {
        "key": "python-pypi",
        "text": "What is the URL for the Python Package Index (PyPI)?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://pypi.org/"}],
        "verification": "manual",
    },
    {
        "key": "stackoverflow-official",
        "text": "What is the Stack Overflow website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://stackoverflow.com/"}],
        "verification": "manual",
    },
    {
        "key": "rust-lang-official",
        "text": "What is the official website for the Rust programming language?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.rust-lang.org/"}],
        "verification": "manual",
    },
    # --- History / Reference (4) ---
    {
        "key": "wikipedia-main",
        "text": "What is the main page of the English Wikipedia?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://en.wikipedia.org/"}],
        "verification": "manual",
    },
    {
        "key": "archive-org",
        "text": "What is the Internet Archive website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://archive.org/"}],
        "verification": "manual",
    },
    {
        "key": "british-museum",
        "text": "What is the official website of the British Museum?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.britishmuseum.org/"}],
        "verification": "manual",
    },
    {
        "key": "smithsonian",
        "text": "What is the official website of the Smithsonian Institution?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.si.edu/"}],
        "verification": "manual",
    },
    # --- Science (4) ---
    {
        "key": "nasa-official",
        "text": "What is the official NASA website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.nasa.gov/"}],
        "verification": "manual",
    },
    {
        "key": "nature-journal",
        "text": "What is the website for the scientific journal Nature?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.nature.com/"}],
        "verification": "manual",
    },
    {
        "key": "arxiv-official",
        "text": "What is the arXiv preprint server website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://arxiv.org/"}],
        "verification": "manual",
    },
    {
        "key": "pubmed",
        "text": "What is the PubMed website for biomedical literature?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://pubmed.ncbi.nlm.nih.gov/"}],
        "verification": "manual",
    },
    # --- Geography / Travel (4) ---
    {
        "key": "google-maps",
        "text": "What is the Google Maps website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://maps.google.com/"}],
        "verification": "manual",
    },
    {
        "key": "openstreetmap",
        "text": "What is the OpenStreetMap website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.openstreetmap.org/"}],
        "verification": "manual",
    },
    {
        "key": "lonely-planet",
        "text": "What is the Lonely Planet travel website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.lonelyplanet.com/"}],
        "verification": "manual",
    },
    {
        "key": "national-geographic",
        "text": "What is the National Geographic website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.nationalgeographic.com/"}],
        "verification": "manual",
    },
    # --- Business (4) ---
    {
        "key": "who-int",
        "text": "What is the official website of the World Health Organization?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.who.int/"}],
        "verification": "manual",
    },
    {
        "key": "reuters",
        "text": "What is the Reuters news website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.reuters.com/"}],
        "verification": "manual",
    },
    {
        "key": "bloomberg",
        "text": "What is the Bloomberg financial news website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.bloomberg.com/"}],
        "verification": "manual",
    },
    {
        "key": "linkedin",
        "text": "What is the LinkedIn website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.linkedin.com/"}],
        "verification": "manual",
    },
    # --- Sports / Culture (4) ---
    {
        "key": "imdb",
        "text": "What is the IMDb (Internet Movie Database) website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.imdb.com/"}],
        "verification": "manual",
    },
    {
        "key": "goodreads",
        "text": "What is the Goodreads book review website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.goodreads.com/"}],
        "verification": "manual",
    },
    {
        "key": "fifa-official",
        "text": "What is the official FIFA website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://www.fifa.com/"}],
        "verification": "manual",
    },
    {
        "key": "olympics-official",
        "text": "What is the official Olympics website?",
        "scoring_unit": "urls",
        "gold": [{"url": "https://olympics.com/"}],
        "verification": "manual",
    },
]


async def seed_vendors(session):
    """Insert or update vendor rows."""
    for v in VENDORS:
        existing = await session.get(Vendor, v["id"])
        if existing:
            existing.enabled = v["enabled"]
            existing.budget_calls = v["budget_calls"]
            existing.budget_period = v["budget_period"]
            print(f"  Updated vendor: {v['id']}")
        else:
            session.add(Vendor(**v))
            print(f"  Created vendor: {v['id']}")
    await session.flush()


async def seed_gold_set(session):
    """Create GoldSet v1 and insert 50 questions."""
    # Check if GoldSet v1 already exists
    result = await session.execute(
        select(GoldSet).where(GoldSet.version == 1)
    )
    gold_set = result.scalar_one_or_none()

    if gold_set is not None:
        # Count existing questions
        q_count = await session.execute(
            select(Question).where(Question.gold_set_id == gold_set.id)
        )
        existing_count = len(q_count.scalars().all())
        print(f"  GoldSet v1 already exists ({existing_count} questions)")
        if existing_count >= 50:
            print("  Already has 50+ questions. Skipping.")
            return
        # Clear existing questions and re-seed
        for q in q_count.scalars().all():
            await session.delete(q)
        await session.flush()
        print("  Cleared existing questions, re-seeding...")
    else:
        gold_set = GoldSet(
            version=1,
            description="Initial gold set: 50 questions (25 entity, 25 URL). "
            "Broad topic mix, 70% easy / 30% medium difficulty.",
            status="draft",
        )
        session.add(gold_set)
        await session.flush()
        print(f"  Created GoldSet v1 (id={gold_set.id})")

    # Insert all 50 questions
    for q in QUESTIONS:
        session.add(
            Question(
                gold_set_id=gold_set.id,
                key=q["key"],
                text=q["text"],
                scoring_unit=q["scoring_unit"],
                gold=q["gold"],
                verification=q["verification"],
            )
        )

    await session.flush()
    print(f"  Inserted {len(QUESTIONS)} questions into GoldSet v1")


async def main():
    async with lifespan(app):
        async with app.state.sessionmaker() as session:
            print("Seeding vendors...")
            await seed_vendors(session)

            print("\nSeeding gold questions...")
            await seed_gold_set(session)

            await session.commit()
            print("\nDone! All data committed.")


if __name__ == "__main__":
    asyncio.run(main())
