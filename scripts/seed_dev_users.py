"""
Seed 10 fake users for local development.
Idempotent — safe to run multiple times (upsert by github_id).

Usage:
    python scripts/seed_dev_users.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.user import User

SEED_USERS = [
    {"github_id": "dev_1001", "github_login": "alice-dev",    "full_name": "Alice Nguyen",    "email": "alice@gmail.com",   "role": "admin"},
    {"github_id": "dev_1002", "github_login": "bob-dev",      "full_name": "Bob Tran",        "email": "bob@gmail.com",     "role": "user"},
    {"github_id": "dev_1003", "github_login": "carol-dev",    "full_name": "Carol Le",        "email": "carol@gmail.com",   "role": "user"},
    {"github_id": "dev_1004", "github_login": "dan-dev",      "full_name": "Dan Pham",        "email": "dan@gmail.com",     "role": "user"},
    {"github_id": "dev_1005", "github_login": "eva-dev",      "full_name": "Eva Hoang",       "email": "eva@gmail.com",     "role": "user"},
    {"github_id": "dev_1006", "github_login": "frank-dev",    "full_name": "Frank Vu",        "email": "frank@gmail.com",   "role": "user"},
    {"github_id": "dev_1007", "github_login": "grace-dev",    "full_name": "Grace Do",        "email": "grace@gmail.com",   "role": "user"},
    {"github_id": "dev_1008", "github_login": "henry-dev",    "full_name": "Henry Bui",       "email": "henry@gmail.com",   "role": "user"},
    {"github_id": "dev_1009", "github_login": "iris-dev",     "full_name": "Iris Dang",       "email": "iris@gmail.com",    "role": "user"},
    {"github_id": "dev_1010", "github_login": "jack-dev",     "full_name": "Jack Ly",         "email": "jack@gmail.com",    "role": "user"},
]


async def seed():
    async with async_session_factory() as session:
        created = 0
        skipped = 0

        for data in SEED_USERS:
            result = await session.execute(
                select(User).where(User.github_id == data["github_id"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                skipped += 1
            else:
                user = User(
                    email=data["email"],
                    full_name=data["full_name"],
                    github_id=data["github_id"],
                    github_login=data["github_login"],
                    role=data["role"],
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                created += 1

        await session.commit()
        if created:
            print(f"[seed] {created} dev users created.")


if __name__ == "__main__":
    asyncio.run(seed())
