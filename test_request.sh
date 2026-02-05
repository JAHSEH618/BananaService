#!/bin/bash
curl -X POST "http://127.0.0.1:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "A futuristic banana city", 
           "model": "gemini-3-pro-image-preview",
           "number_of_images": 1
         }'
