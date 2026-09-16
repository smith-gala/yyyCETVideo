from app.services.ai_service import AIService


def test_ai_jointly_aligns_bilingual_cues_without_retranslating(monkeypatch):
    service = AIService()
    units = [{
        "english": (
            "In recent years, Northeast China has been vigorously developing "
            "its ice and snow resources."
        ),
        "chinese": "近年来，中国东北地区正在大力开发冰雪资源。",
    }]

    monkeypatch.setattr(
        service,
        "_call_llm_json",
        lambda prompt, max_tokens: {
            "sentences": [{
                "sentence_id": 1,
                "cues": [
                    {
                        "english": "In recent years, Northeast China",
                        "chinese": "近年来，中国东北地区",
                    },
                    {
                        "english": "has been vigorously developing its ice and snow resources.",
                        "chinese": "正在大力开发冰雪资源。",
                    },
                ],
            }],
        },
    )

    aligned = service.align_subtitle_cues(units)

    assert aligned is not None
    assert aligned[0]["subtitle_cues"] == [
        {
            "english": "In recent years, Northeast China",
            "chinese": "近年来，中国东北地区",
        },
        {
            "english": "has been vigorously developing its ice and snow resources.",
            "chinese": "正在大力开发冰雪资源。",
        },
    ]
    assert " ".join(cue["english"] for cue in aligned[0]["subtitle_cues"]) == units[0]["english"]
    assert "".join(cue["chinese"] for cue in aligned[0]["subtitle_cues"]) == units[0]["chinese"]


def test_ai_alignment_rejects_rewritten_or_missing_source_chinese(monkeypatch):
    service = AIService()
    units = [{
        "english": (
            "In recent years, Northeast China has been vigorously developing "
            "its ice and snow resources."
        ),
        "chinese": "近年来，中国东北地区正在大力开发冰雪资源。",
    }]
    monkeypatch.setattr(
        service,
        "_call_llm_json",
        lambda prompt, max_tokens: {
            "sentences": [{
                "sentence_id": 1,
                "cues": [
                    {
                        "english": "In recent years, Northeast China",
                        "chinese": "近些年，中国东北",
                    },
                    {
                        "english": "has been vigorously developing its ice and snow resources.",
                        "chinese": "大力发展冰雪资源。",
                    },
                ],
            }],
        },
    )

    assert service.align_subtitle_cues(units) is None


def test_ai_alignment_repairs_only_the_overlong_sentence(monkeypatch):
    service = AIService()
    units = [
        {
            "english": "In recent years, China's drone industry has experienced rapid development.",
            "chinese": "近年来，中国无人机产业迅猛发展。",
        },
        {
            "english": (
                "Thanks to their excellent stability, high-definition imaging capabilities, "
                "and user-friendly operation, Chinese drones have gained widespread popularity."
            ),
            "chinese": "中国无人机凭借其出色的稳定性、高清成像能力和便捷的操作性，深受全球消费者的青睐。",
        },
    ]
    calls = []

    def fake_call(prompt, max_tokens):
        calls.append(prompt)
        if len(calls) == 1:
            return {
                "sentences": [
                    {"sentence_id": 1, "cues": [units[0]]},
                    {"sentence_id": 2, "cues": [units[1]]},
                ]
            }
        return {
            "cues": [
                {
                    "english": "Thanks to their excellent stability, high-definition imaging capabilities,",
                    "chinese": "中国无人机凭借其出色的稳定性、高清成像能力",
                },
                {
                    "english": "and user-friendly operation, Chinese drones have gained widespread popularity.",
                    "chinese": "和便捷的操作性，深受全球消费者的青睐。",
                },
            ]
        }

    monkeypatch.setattr(service, "_call_llm_json", fake_call)

    aligned = service.align_subtitle_cues(units)

    assert aligned is not None
    assert len(calls) == 2
    assert "第2句" in calls[1]
    assert aligned[0]["subtitle_cues"] == [units[0]]
    assert len(aligned[1]["subtitle_cues"]) == 2


def test_ai_alignment_uses_safe_local_split_when_sentence_retry_still_overflows(monkeypatch):
    service = AIService()
    unit = {
        "english": (
            "Thanks to their excellent stability, high-definition imaging capabilities, "
            "and user-friendly operation, Chinese drones have gained widespread popularity "
            "among global consumers and found extensive applications in civil sectors."
        ),
        "chinese": (
            "中国无人机凭借其出色的稳定性、高清成像能力和便捷的操作性，"
            "深受全球消费者的青睐，在民用领域得到了广泛应用。"
        ),
    }
    monkeypatch.setattr(
        service,
        "_call_llm_json",
        lambda prompt, max_tokens: {
            "sentences": [{"sentence_id": 1, "cues": [unit]}]
        },
    )

    aligned = service.align_subtitle_cues([unit])

    assert aligned is not None
    cues = aligned[0]["subtitle_cues"]
    assert len(cues) > 1
    assert " ".join(cue["english"] for cue in cues) == unit["english"]
    assert "".join(cue["chinese"] for cue in cues) == unit["chinese"]
    assert all(service._validate_subtitle_cues([cue], cue)[1] is None for cue in cues)


def test_ai_alignment_repairs_an_empty_cue_instead_of_treating_it_as_rewritten_text(monkeypatch):
    service = AIService()
    unit = {
        "english": "Drones enable swift delivery of fresh produce.",
        "chinese": "无人机能够快速配送新鲜农产品。",
    }
    responses = iter([
        {
            "sentences": [{
                "sentence_id": 1,
                "cues": [unit, {"english": "", "chinese": ""}],
            }],
        },
        {"cues": [unit]},
    ])
    monkeypatch.setattr(
        service,
        "_call_llm_json",
        lambda prompt, max_tokens: next(responses),
    )

    aligned = service.align_subtitle_cues([unit])

    assert aligned is not None
    assert aligned[0]["subtitle_cues"] == [unit]
