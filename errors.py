"""Turns errors into plain-English messages. The technical text is still shown under
'Technical details' so it can be passed to support."""
import json

import anthropic

SETTINGS = "An admin can fix this on the ⚙️ Settings page."


def friendly(exc: Exception) -> str:
    text = str(exc).lower()

    # Claude API
    if "no claude api key" in text:
        return f"No Claude API key is set yet, so questions can't be answered. {SETTINGS}"
    if isinstance(exc, anthropic.AuthenticationError):
        return f"The Claude API key was rejected (it may have been deleted or mistyped). {SETTINGS}"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"The Claude API key isn't allowed to use this model. {SETTINGS}"
    if isinstance(exc, anthropic.BadRequestError) and "credit" in text:
        return ("The Claude API account has run out of credit. "
                "Ask an admin to add billing at platform.claude.com.")
    if isinstance(exc, anthropic.RateLimitError):
        return "Too many questions at once. Wait a minute, then try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Couldn't reach Claude. Check this computer's internet connection, then try again."
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return "Claude is temporarily unavailable. Try again in a few minutes."

    # Bookings server
    if "no password saved" in text:
        return f"The bookings server password isn't saved yet. {SETTINGS}"
    if "adomd.net was not found" in text:
        return ("The connector for the bookings server (ADOMD.NET) is missing. "
                "Run 'python get_adomd.py' in the app folder (see README).")
    if any(s in text for s in ("logon failure", "user name or password is incorrect",
                               "login failed", "access denied", "not have permission")):
        return f"The bookings server didn't accept the username or password. {SETTINGS}"
    if any(s in text for s in ("a connection cannot be made", "forcibly closed",
                               "no connection could be made", "timed out", "host is unknown")):
        return ("Couldn't connect to the bookings server. Check the network connection and try "
                f"again. If it keeps happening, the server login may be wrong. {SETTINGS}")

    # The query itself
    if any(s in text for s in ("composite key", "query (", "does not start with evaluate",
                               "binder error", "parser error", "catalog error")):
        return ("Claude couldn't write a query the bookings data accepts for this question "
                "(it tried twice). Try rephrasing: name the number (e.g. sales, profit, bookings) "
                "and the period, or ask for a simpler breakdown.")
    if "dashboard dates" in text:
        return ("Claude couldn't make this chart follow the dashboard's dates. Try rephrasing the "
                "question, or choose 'All dates' for this chart.")
    if isinstance(exc, json.JSONDecodeError):
        return "Claude's answer came back in an unexpected format. Please try again."
    if isinstance(exc, RuntimeError) and str(exc):
        return str(exc)  # our own messages are already written for users

    return ("Something went wrong while answering. Try again or rephrase the question. "
            "If it keeps happening, send the technical details below to your admin.")


def details(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"
