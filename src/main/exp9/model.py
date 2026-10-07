from langchain_aws import ChatBedrockConverse

from ..bedrock import MODEL, PROFILE, REGION


def model(max_tokens: int = 1024) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=MODEL,
        region_name=REGION,
        credentials_profile_name=PROFILE,
        max_tokens=max_tokens,
    )
