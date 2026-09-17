from main.bedrock import MODEL, async_client


async def test_sonnet_46_responds():
    c = async_client()
    r = await c("Say OK and nothing else.")
    assert "OK" in r.content[0].text
    assert MODEL == "us.anthropic.claude-sonnet-4-6"
