#!/usr/bin/env python3
"""
Test script for DeepSeek API
"""
import asyncio
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

async def test_deepseek_api():
    """Test DeepSeek API connection"""
    print("Testing DeepSeek API...")
    
    # Get API key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key found")
    print(f"Base URL: {base_url}")
    
    if not api_key:
        print("❌ No DeepSeek API key found!")
        return
    
    try:
        # Initialize LLM
        llm = ChatOpenAI(
            model="deepseek-chat",
            openai_api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            max_tokens=100
        )
        
        print("✅ LLM initialized successfully")
        
        # Test simple message
        print("Testing simple message...")
        response = await llm.ainvoke([{"role": "user", "content": "Hello, say hi back"}])
        
        print(f"✅ Response received: {response.content}")
        
        # Test streaming
        print("Testing streaming...")
        async for chunk in llm.astream([{"role": "user", "content": "Say hello in 3 words"}]):
            content = chunk.content if hasattr(chunk, 'content') else ""
            if content:
                print(f"Stream chunk: {content}")
        
        print("✅ Streaming test completed")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_deepseek_api()) 