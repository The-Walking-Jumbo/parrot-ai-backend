import httpx
import json
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def execute_pre_call_tools(assistant_id: str, metadata: Dict[str, Any]):
    """Execute all pre-call tools for an assistant"""
    from core.database import db_client
    
    result = await db_client.execute(
        "SELECT name, tool_type, config FROM pre_call_tools WHERE assistant_id = ? AND is_active = 1 ORDER BY execution_order ASC",
        [assistant_id]
    )
    
    for row in result.rows:
        name, tool_type, config_str = row
        try:
            config = json.loads(config_str)
            logger.info(f"Executing pre-call tool: {name}")
            
            if tool_type == "http_request":
                await execute_http_tool(config, metadata)
            elif tool_type == "database_query":
                await execute_db_query_tool(config, metadata)
        except Exception as e:
            logger.error(f"Failed to execute pre-call tool {name}: {e}")

async def execute_post_call_tools(assistant_id: str, call_id: str, transcript: str, metadata: Dict[str, Any]):
    """Execute all post-call tools for an assistant"""
    from core.database import db_client
    
    result = await db_client.execute(
        "SELECT name, tool_type, config FROM post_call_tools WHERE assistant_id = ? AND is_active = 1 ORDER BY execution_order ASC",
        [assistant_id]
    )
    
    metadata['transcript'] = transcript
    metadata['call_id'] = call_id
    
    for row in result.rows:
        name, tool_type, config_str = row
        try:
            config = json.loads(config_str)
            logger.info(f"Executing post-call tool: {name}")
            
            if tool_type == "http_request":
                await execute_http_tool(config, metadata)
            elif tool_type == "email_send":
                await execute_email_tool(config, metadata)
        except Exception as e:
            logger.error(f"Failed to execute post-call tool {name}: {e}")

async def execute_http_tool(config: Dict, metadata: Dict):
    """Execute HTTP request tool"""
    url = replace_variables(config.get('url', ''), metadata)
    method = config.get('method', 'GET')
    headers = config.get('headers', {})
    body_str = json.dumps(config.get('body', {}))
    body = json.loads(replace_variables(body_str, metadata))
    
    async with httpx.AsyncClient() as client:
        try:
            if method == 'GET':
                response = await client.get(url, headers=headers)
            elif method == 'POST':
                response = await client.post(url, headers=headers, json=body)
            elif method == 'PATCH':
                response = await client.patch(url, headers=headers, json=body)
            else:
                return None
                
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"HTTP tool error: {e}")
            return None

async def execute_db_query_tool(config: Dict, metadata: Dict):
    """Execute database query tool"""
    # Placeholder for actual dynamic DB connection executing logic
    logger.info("Executing DB Query Tool (Placeholder)")
    pass

async def execute_email_tool(config: Dict, metadata: Dict):
    """Send email after call"""
    # Placeholder for SMTP integration
    logger.info("Executing Email Tool (Placeholder)")
    pass

def replace_variables(template: str, metadata: Dict) -> str:
    """Replace {{variable}} with values from metadata"""
    def replacer(match):
        var_name = match.group(1)
        return str(metadata.get(var_name, ''))
    
    return re.sub(r'\{\{(\w+)\}\}', replacer, template)
