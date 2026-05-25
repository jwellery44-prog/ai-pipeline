import asyncio
import httpx

API_KEY = "366060ed2f3a25e5640ed861e43a15ac"
URL = "https://api.nanobananaapi.ai/api/v1/nanobanana/generate-2"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
IMAGE_URL = "https://images.unsplash.com/photo-1617038260897-41a1f14a8ca0?q=80&w=1000&auto=format&fit=crop"

async def test_payload(name, payload):
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"Testing {name}...")
            response = await client.post(URL, headers=headers, json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}\n")
        except Exception as e:
            print(f"Error testing {name}: {e}\n")

async def main():
    # Test 1: Standard 1K
    await test_payload("1K Standard", {
        "prompt": "Place on a beautiful marble table",
        "imageUrls": [IMAGE_URL],
        "resolution": "1K",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

    # Test 2: Standard 2K
    await test_payload("2K Standard", {
        "prompt": "Place on a beautiful marble table",
        "imageUrls": [IMAGE_URL],
        "resolution": "2K",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

    # Test 3: Standard 4K
    await test_payload("4K Standard", {
        "prompt": "Place on a beautiful marble table",
        "imageUrls": [IMAGE_URL],
        "resolution": "4K",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

    # Test 4: Lowercase 2k
    await test_payload("2k Lowercase", {
        "prompt": "Place on a beautiful marble table",
        "imageUrls": [IMAGE_URL],
        "resolution": "2k",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

    # Test 5: Lowercase 4k
    await test_payload("4k Lowercase", {
        "prompt": "Place on a beautiful marble table",
        "imageUrls": [IMAGE_URL],
        "resolution": "4k",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

    # Test 6: Text-to-image 2K (empty imageUrls)
    await test_payload("Text-to-image 2K", {
        "prompt": "A beautiful diamond ring on a marble table, professional product photography",
        "imageUrls": [],
        "resolution": "2K",
        "callBackUrl": "https://api.nanobananaapi.ai/callback"
    })

if __name__ == "__main__":
    asyncio.run(main())
