---
title: RoofersParadise
emoji: 🌩️
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
---

# RoofersParadise

A free hail map for roofers -- see where hail hit (NOAA MRMS radar), look up any address, and
get real-time alerts. Free alternative to paid storm-tracking tools.

One FastAPI app: serves the map + Google sign-in + alerts UI. Deployed on Hugging Face Spaces
(Docker, free, 16GB RAM) with accounts in Turso and the poller/refresh in GitHub Actions.
See DEPLOY.md for details. Not affiliated with the National Weather Service.
