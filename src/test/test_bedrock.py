from main.bedrock import MODEL, async_client


async def test_the_configured_model_responds():
    c = async_client()
    r = await c("Say OK and nothing else.")
    assert "OK" in r.content[0].text
    assert MODEL.startswith("us.anthropic.claude-")
