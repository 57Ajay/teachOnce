import json

import pytest

import config
import meta_client


def test_replay_serves_cassette_and_never_hits_network(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CASSETTE_DIR", tmp_path)
    monkeypatch.setattr(config, "META_CACHE", "replay")
    body = {"model": meta_client.SPARK, "input": "hi"}
    with pytest.raises(meta_client.MetaAPIError, match="no cassette"):
        meta_client.responses(**body)

    canned = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "pong"}]}]}
    meta_client._cassette(["/responses", body]).write_text(json.dumps(canned))
    assert meta_client.output_text(meta_client.responses(**body)) == "pong"
