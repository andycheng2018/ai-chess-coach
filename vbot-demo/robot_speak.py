#!/usr/bin/env python3
"""Say one short text through the dog's built-in voice. The text arrives on stdin.

The only route this helper can call is /speech/set_speak, so it has no path to a
head, body or navigation command. It deliberately ignores the controller lock: that
lock guards motion, and an idle VBOT Studio connection holds it for minutes at a time.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import sys
import uuid

SESSION = "/opt/vita/aorta/edu/edu_session.json5"
VERSIONS = {"aorta-sdk": "2026.9.23", "aorta-msgs": "2026.9.23", "vbot-edu-msgs": "2026.9.24", "flatbuffers": "25.12.19"}
ROUTE = "/speech/set_speak"
HUMAN_VOICE, START_PLAYING = 1, 1
MAX_CHARS = 400
CALL_TIMEOUT_MS = 30000


def emit(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


def clean(raw):
    """Models can leak reasoning or markup; none of it should be read aloud."""
    text = re.sub(r"<think>.*?(</think>|$)", " ", raw, flags=re.S | re.I)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return " ".join(text.split())[:MAX_CHARS].strip()


def text_of(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def speak(text, pre_check, request_id, node=None):
    os.environ["ZENOH_SESSION_CONFIG_URI"] = SESSION
    import aorta as sdk
    import set_speak_schema_meta as schema
    from aorta.services.speech.SetSpeakResponse import SetSpeakResponse

    def fill(builder, header):
        identifier = builder.CreateString(request_id)
        words = builder.CreateString(text)
        schema.SetSpeakRequestStart(builder)
        schema.SetSpeakRequestAddAortaHeader(builder, header)
        schema.SetSpeakRequestAddTargetState(builder, START_PLAYING)
        schema.SetSpeakRequestAddMode(builder, HUMAN_VOICE)
        schema.SetSpeakRequestAddReqId(builder, identifier)
        schema.SetSpeakRequestAddPreCheck(builder, pre_check)
        schema.SetSpeakRequestAddHumanLanguageText(builder, words)
        return schema.SetSpeakRequestEnd(builder)

    def call(active):
        options = sdk.ClientOptions(timeout_ms=CALL_TIMEOUT_MS, enforce_single_provider=True, allow_retry=False)
        with active.create_client_typed(ROUTE, SetSpeakResponse.GetRootAs, request_schema_meta=schema, options=options) as client:
            response = client.call(fill).decode()
        return response.Status(), response.ErrorCode(), text_of(response.Message())[:300]
    if node is not None:
        return call(node)
    with sdk.Node("edu_sdk") as own:
        return call(own)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-check", action="store_true", help="Ask the speech service to validate only; makes no sound")
    args = parser.parse_args(argv)
    request_id = uuid.uuid4().hex

    def refuse(code, reason):
        emit(event="speak_refused", requestId=request_id, code=code, reason=reason)
        return 1
    text = clean(sys.stdin.read(MAX_CHARS * 8))
    if not text:
        return refuse("empty", "There is nothing to say.")
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version:
            return refuse("sdk", f"Install the documented SDK pairing: {name}=={version}")
    if not os.access(SESSION, os.R_OK):
        return refuse("sdk", "The documented EDU session file is unavailable.")
    status, error_code, message = speak(text, args.pre_check, request_id)
    spoken = status == 0 and error_code == 0
    emit(event="speak_result", requestId=request_id, ok=spoken, preCheck=args.pre_check, chars=len(text),
         status=status, errorCode=error_code, message=message)
    return 0 if spoken else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(event="error", error=type(error).__name__, message="The speech helper failed. Check the SDK setup on the dog.")
        raise SystemExit(1)
