
## 2023-10-27 - PyMuPDF get_image_info(xrefs=True) is a severe bottleneck
**Learning:** In PyMuPDF, `page.get_image_info(xrefs=True)` calculates the MD5 hash for EVERY drawn image on the page to match it with the xref from the document resources. This causes processing time to skyrocket (e.g., 4s per page vs 0.002s without xrefs).
**Action:** Always use `page.get_image_info(xrefs=False)` to get bounding boxes. If xrefs are needed, manually match the image dimensions with `page.get_images()` and verify the bounding box using `page.get_image_rects(xref)`. This avoids hashing and speeds up page processing by orders of magnitude.
