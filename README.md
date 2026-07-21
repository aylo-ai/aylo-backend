# AI Service

The brain behind Repli's chatbot. It reads an incoming customer message, decides
what to do, and replies in natural language — on any channel, in real time.

Powered entirely by **OpenAI** (chat, vision, voice, and vector-store knowledge).

## What it does

- **Answers customers automatically** — holds a real conversation, keeps context,
  and stays on-brand using each assistant's own instructions.
- **Understands more than text** — reads photos and transcribes voice notes, so a
  customer can just snap a picture or speak.
- **Knows the business** — searches the assistant's uploaded documents (its
  knowledge base) before answering, instead of guessing.
- **Captures leads** — collects name, phone, and product interest, confirms the
  details with the customer, then records the lead for the sales team.
- **Hands off to humans** — escalates the moment a customer asks for a person, gets
  upset, or the bot genuinely can't help.
- **Follows up** — schedules a later message when a customer says they need time to
  think or will decide later.
- **Remembers the thread** — can look back over recent messages instead of asking
  the customer to repeat themselves.
- **Optional web search** — can look things up online when an assistant has it
  enabled.

## Where it works

One assistant, every channel: **Telegram, WhatsApp, Instagram, website widget,
email, SMS, and phone.** Replies are pushed live over websocket so they appear
instantly.

## Knowledge base

Each assistant has its own knowledge base of uploaded files. Documents are indexed
into an OpenAI vector store; when files change, a fresh store is built and swapped
in only once it's ready — so a failed update never wipes out what the bot already
knows. (Assistants migrated from the old Gemini setup keep answering while their
files are re-indexed.)

## Built to never break the conversation

- A failing tool or a bad file comes back to the model as a note it can work
  around — it never crashes the reply.
- If OpenAI is slow or down, the customer still gets a graceful fallback message
  and a human is looped in.
- Every reply is stored, so nothing is lost.
