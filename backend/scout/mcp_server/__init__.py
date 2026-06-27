"""Phase 1 — custom MCP server wrapping the Shopify Admin API.

The agent is an MCP *client* and never imports Shopify directly. Auth, rate limiting,
and pagination are handled here and must not leak to the agent.
"""
