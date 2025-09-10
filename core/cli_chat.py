from typing import List, Tuple
from mcp.types import Prompt, PromptMessage
from anthropic.types import MessageParam

from core.chat import Chat
from core.claude import Claude
from mcp_client import MCPClient


def _split_resource_path(resource_path: str) -> tuple[str, str]:
    """
    Accepts "meetings/987654321" or "meetings:987654321".
    Returns (resource_type, resource_id).
    """
    if "/" in resource_path:
        rtype, rid = resource_path.split("/", 1)
    elif ":" in resource_path:
        rtype, rid = resource_path.split(":", 1)
    else:
        raise ValueError(
            "Resource path must be 'type/id' or 'type:id', e.g., 'meetings/987654321'."
        )
    return rtype.strip(), rid.strip()


class CliChat(Chat):
    def __init__(
        self,
        doc_client: MCPClient,
        clients: dict[str, MCPClient],
        claude_service: Claude,
    ):
        super().__init__(clients=clients, claude_service=claude_service)
        self.doc_client: MCPClient = doc_client

    async def list_prompts(self) -> list[Prompt]:
        return await self.doc_client.list_prompts()

    # ----------------- UPDATED FOR ZOOM WORKPLACE RESOURCES -----------------
    async def list_docs_ids(self) -> list[str]:
        """
        Returns a flat list of "type/id" strings for convenience, e.g.:
          ["meetings/987654321", "team_chat/msg_1001", "mail/email_2001", ...]
        """
        mapping = await self.doc_client.read_resource("res://resources")
        # mapping is expected to be: { "meetings": [...], "team_chat": [...], "mail": [...], "calendar": [...] }
        flat = [f"{rtype}/{rid}" for rtype, ids in mapping.items() for rid in ids]
        # Stable ordering helps deterministic prompts/tests
        return sorted(flat, key=str)

    async def get_doc_content(self, doc_id: str) -> dict:
        """
        Fetch a specific Zoom Workplace item using combined "type/id".
        Accepts "type/id" or "type:id".
        """
        rtype, rid = _split_resource_path(doc_id)
        return await self.doc_client.read_resource(f"res://resources/{rtype}/{rid}")
    # -----------------------------------------------------------------------

    async def get_prompt(
        self, command: str, doc_id: str
    ) -> list[PromptMessage]:
        # For backward compatibility, we still pass a single "doc_id" arg.
        # Ensure callers supply "type/id" (e.g., "meetings/987654321").
        return await self.doc_client.get_prompt(command, {"doc_id": doc_id})

    async def _extract_resources(self, query: str) -> str:
        """
        Finds @mentions in the query and inlines their resource content.

        Supports: @meetings/987654321 or @meetings:987654321
        """
        # Raw mentions without the "@" prefix
        mentions = [word[1:] for word in query.split() if word.startswith("@")]

        # Build a fast lookup set from available "type/id"
        all_ids = await self.list_docs_ids()
        all_ids_set = set(all_ids)

        mentioned_docs: list[Tuple[str, dict]] = []

        # Normalize each mention to "type/id"
        normalized_mentions = []
        for m in mentions:
            if ":" in m:
                rtype, rid = _split_resource_path(m)
                normalized_mentions.append(f"{rtype}/{rid}")
            else:
                normalized_mentions.append(m)

        # Only pull those that actually exist in the MCP resources
        for doc_id in normalized_mentions:
            if doc_id in all_ids_set:
                content = await self.get_doc_content(doc_id)
                mentioned_docs.append((doc_id, content))

        return "".join(
            f'\n<resource id="{doc_id}">\n{content}\n</resource>\n'
            for doc_id, content in mentioned_docs
        )

    async def _process_command(self, query: str) -> bool:
        if not query.startswith("/"):
            return False

        words = query.split()
        command = words[0].replace("/", "")

        # Expect "type/id" after the command, e.g. `/summarize meetings/987654321`
        target = words[1] if len(words) > 1 else ""
        messages = await self.doc_client.get_prompt(command, {"doc_id": target})

        self.messages += convert_prompt_messages_to_message_params(messages)
        return True

    async def _process_query(self, query: str):
        if await self._process_command(query):
            return

        added_resources = await self._extract_resources(query)

        prompt = f"""
        The user has a question:
        <query>
        {query}
        </query>

        The following context may be useful in answering their question:
        <context>
        {added_resources}
        </context>

        Notes:
        - Users may reference Zoom Workplace resources with mentions like "@meetings/987654321" or "@team_chat/msg_1001".
        - The "@" is only a mention marker; the actual resource key is "type/id".
        - If the resource content is already included above, do not call additional tools to fetch it again.

        Answer the user's question directly and concisely. Start with the exact information they need.
        Do not refer to the provided context explicitly; just use it to inform your answer.
        """

        self.messages.append({"role": "user", "content": prompt})


def convert_prompt_message_to_message_param(
    prompt_message: "PromptMessage",
) -> MessageParam:
    role = "user" if prompt_message.role == "user" else "assistant"

    content = prompt_message.content

    # Check if content is a dict-like object with a "type" field
    if isinstance(content, dict) or hasattr(content, "__dict__"):
        content_type = (
            content.get("type", None)
            if isinstance(content, dict)
            else getattr(content, "type", None)
        )
        if content_type == "text":
            content_text = (
                content.get("text", "")
                if isinstance(content, dict)
                else getattr(content, "text", "")
            )
            return {"role": role, "content": content_text}

    if isinstance(content, list):
        text_blocks = []
        for item in content:
            # Check if item is a dict-like object with a "type" field
            if isinstance(item, dict) or hasattr(item, "__dict__"):
                item_type = (
                    item.get("type", None)
                    if isinstance(item, dict)
                    else getattr(item, "type", None)
                )
                if item_type == "text":
                    item_text = (
                        item.get("text", "")
                        if isinstance(item, dict)
                        else getattr(item, "text", "")
                    )
                    text_blocks.append({"type": "text", "text": item_text})

        if text_blocks:
            return {"role": role, "content": text_blocks}

    return {"role": role, "content": ""}


def convert_prompt_messages_to_message_params(
    prompt_messages: List[PromptMessage],
) -> List[MessageParam]:
    return [
        convert_prompt_message_to_message_param(msg) for msg in prompt_messages
    ]
