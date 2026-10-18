# OCR model attribution

This project bundles the unchanged ONNX files supplied with RapidOCR 3.10.0:

- PP-OCRv6_det_small.onnx
- PP-OCRv6_rec_small.onnx
- ch_ppocr_mobile_v2.0_cls_mobile.onnx

The upstream weights are attributed to Baidu and the PaddleOCR rights holders. RapidOCR packages/converts them for inference. The models are distributed under Apache-2.0, separately from the RapidOCR source authorship. No Microsoft font files or upstream game artwork are redistributed.

Source: https://rapidai.github.io/RapidOCRDocs/main/model_licenses/

The exact hashes in this distribution are recorded in `research/ocr_model_manifest.json` in the source project. Apache-2.0 and dependency notices accompany this package. The upstream default model manifest is also included with the rapidocr package inside the application.
