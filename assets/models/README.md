# Modelos de detecção de cara

## YuNet (`face_detection_yunet_2023mar.onnx`)

- Origem: [OpenCV Zoo — Face Detection YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
- Licença: **Apache License 2.0** (ver o repositório opencv_zoo)
- Utilização: detector DNN headless via `cv2.FaceDetectorYN` (OpenCV 4.5.4+).
- O Haar Cascade da OpenCV continua como *fallback* se o ONNX não carregar; se nenhum detector encontrar uma cara, a fotografia é **rejeitada** (não se publica com desfoque geométrico).
