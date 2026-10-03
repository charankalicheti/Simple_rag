import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import bcrypt
import httpx
from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-key-change-before-deploying")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))


def get_db():
    with SessionLocal() as db:
        yield db


DbSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Daylight AI", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=os.getenv("COOKIE_HTTPS_ONLY", "false").lower() == "true",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STARTER_IDEAS = [
    {
        "category": "A fresh perspective",
        "title": "Make room for the useful question",
        "body": "Before reaching for an answer, write down what you are actually trying to change. A clearer question often makes the next step surprisingly small.",
        "time": "2 min read",
        "color": "mint",
    },
    {
        "category": "A small experiment",
        "title": "Turn one idea into a 15-minute test",
        "body": "Pick the part of your idea you feel least certain about. Find the quickest low-stakes way to learn whether it holds up, then let the result guide your next move.",
        "time": "Try today",
        "color": "peach",
    },
    {
        "category": "A useful prompt",
        "title": "What would make this easier?",
        "body": "Ask an AI assistant to list three ways to simplify a task you have been putting off. Choose the least impressive-sounding option; it is often the easiest one to begin.",
        "time": "Save for later",
        "color": "blue",
    },
]


def render(request: Request, page: str, **context):
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return templates.TemplateResponse(
        request=request,
        name=page,
        context={
            "user_name": request.session.get("user_name"),
            "csrf_token": request.session["csrf_token"],
            **context,
        },
    )


def valid_csrf(request: Request, token: str) -> bool:
    expected = request.session.get("csrf_token", "")
    return bool(expected) and secrets.compare_digest(expected, token)


def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return db.get(User, user_id)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: DbSession):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "home.html", ideas=STARTER_IDEAS, ai_enabled=bool(AI_API_KEY))


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "register.html")


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    db: DbSession,
    name: Annotated[str, Form(min_length=2, max_length=80)],
    email: Annotated[str, Form(max_length=254)],
    password: Annotated[str, Form(min_length=8, max_length=72)],
    csrf_token: Annotated[str, Form()],
):
    clean_email = email.strip().lower()
    if not valid_csrf(request, csrf_token):
        return render(request, "register.html", error="Your session expired. Please try again.")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean_email):
        return render(request, "register.html", error="Enter a valid email address.")
    if len(password.encode()) > 72:
        return render(request, "register.html", error="Password must be no more than 72 bytes.")
    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing:
        return render(request, "register.html", error="An account with that email already exists.")
    user = User(
        name=name.strip(),
        email=clean_email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    if not valid_csrf(request, csrf_token):
        return render(request, "login.html", error="Your session expired. Please try again.")
    if len(password.encode()) > 72:
        return render(request, "login.html", error="That email and password do not match.")
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    valid = user is not None and bcrypt.checkpw(password.encode(), user.password_hash.encode())
    if not valid:
        return render(request, "login.html", error="That email and password do not match.")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
def logout(request: Request, csrf_token: Annotated[str, Form()]):
    if not valid_csrf(request, csrf_token):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/api/ideas", response_class=HTMLResponse)
async def generate_ideas(request: Request):
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not valid_csrf(request, csrf_token):
        return render(request, "home.html", ideas=STARTER_IDEAS, ai_enabled=bool(AI_API_KEY), error="Your session expired. Please try again.")
    if not AI_API_KEY:
        return render(
            request,
            "home.html",
            ideas=STARTER_IDEAS,
            ai_enabled=False,
            notice="Add an AI_API_KEY to your environment to generate a fresh set of ideas.",
        )
    prompt = "Create three concise, practical, encouraging AI-generated ideas for a personal creativity dashboard. Return a JSON object with an 'ideas' array. Each item has category, title, body, time, and color. Use mint, peach, or blue for color."
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
                json={
                    "model": AI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        payload = response.json()["choices"][0]["message"]["content"]
        decoded = json.loads(payload)
        ideas = decoded.get("ideas", decoded) if isinstance(decoded, dict) else decoded
        if not isinstance(ideas, list):
            raise ValueError("AI response did not contain a list")
        ideas = [
            {
                "category": str(item.get("category", "A fresh perspective"))[:60],
                "title": str(item.get("title", "A new idea"))[:100],
                "body": str(item.get("body", ""))[:500],
                "time": str(item.get("time", "A moment to explore"))[:40],
                "color": item.get("color") if item.get("color") in {"mint", "peach", "blue"} else "mint",
            }
            for item in ideas[:3]
            if isinstance(item, dict)
        ]
        if not ideas:
            raise ValueError("AI response was empty")
        return render(request, "home.html", ideas=ideas, ai_enabled=True, notice="Fresh ideas, just for you.")
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return render(
            request,
            "home.html",
            ideas=STARTER_IDEAS,
            ai_enabled=True,
            error="Ideas could not be generated right now. Your saved starter ideas are still here.",
        )