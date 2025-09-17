import os
from datetime import datetime
from typing import Any, Optional, Tuple, Dict

import cv2 as cv
import numpy as np
import skimage as ski

# for gds loading
from klayout import lay

# Sift detection moved over to skimage since I prefer it.
from skimage.feature import SIFT, ORB, match_descriptors


class Preprocessor:
    """
    Handles preprocessing of images and masks for affine registration.
    Settings control operations like blur, invert, equalize, canny edge detection, and sigma values.
    """

    def __init__(self) -> None:
        self.settings: Dict[str, Any] = {
            "blurmask": False,
            "invertmask": False,
            "equalizemask": False,
            "cannymask": False,
            "otsumask": False,
            "manualthresholdmask": False,
            "thresholdmask": 128,
            "morphologymask": False,
            "morphologytypemask": "erosion",
            "morphologystrengthmask": 3,
            "blurimage": False,
            "invertimage": False,
            "equalizeimage": False,
            "cannyimage": False,
            "otsuimage": False,
            "manualthresholdimage": False,
            "thresholdimage": 128,
            "morphologyimage": False,
            "morphologytypeimage": "erosion",
            "morphologystrengthimage": 3,
            "sigmaimage": 1.0,
            "sigmamask": 1.0,
        }

    def update_settings(self, settings_dict: Dict[str, Any]) -> None:
        """
        Update preprocessing settings from a dictionary.
        Args:
            settings_dict (dict): Dictionary of preprocessing settings.
        """
        self.settings.update(settings_dict)

    def preprocess_img(self, img: np.ndarray) -> np.ndarray:
        """
        Preprocesses an image according to current settings.
        Args:
            img (np.ndarray): Input image (RGB or grayscale).
        Returns:
            np.ndarray: Preprocessed image (uint8, grayscale).
        """
        s = self.settings
        if len(img.shape) == 3:
            img = ski.color.rgb2gray(img)
        if s["invertimage"]:
            img = 1.0 - img
        if s["equalizeimage"]:
            img = ski.exposure.equalize_hist(img)
        if s["blurimage"]:
            img = ski.filters.gaussian(img, sigma=s["sigmaimage"])
        if s["cannyimage"]:
            img = ski.feature.canny(img, sigma=s["sigmaimage"])
            img = img.astype(float)
        if s["otsuimage"]:
            # Convert to uint8 for threshold_otsu
            img_uint8 = (img * 255).astype("uint8")
            threshold = ski.filters.threshold_otsu(img_uint8)
            img = img_uint8 > threshold
            img = img.astype(float)
        if s["manualthresholdimage"]:
            # Convert to uint8 for manual threshold
            img_uint8 = (img * 255).astype("uint8")
            img = img_uint8 > s["thresholdimage"]
            img = img.astype(float)
        if s["morphologyimage"]:
            # Apply morphological operations
            img_binary = (img > 0.5).astype(bool) if img.max() <= 1.0 else (img > 127).astype(bool)
            morph_type = s["morphologytypeimage"]
            strength = s["morphologystrengthimage"]
            kernel = ski.morphology.disk(strength)

            if morph_type == "erosion":
                img_binary = ski.morphology.erosion(img_binary, kernel)
            elif morph_type == "dilation":
                img_binary = ski.morphology.dilation(img_binary, kernel)
            elif morph_type == "opening":
                img_binary = ski.morphology.opening(img_binary, kernel)
            elif morph_type == "closing":
                img_binary = ski.morphology.closing(img_binary, kernel)

            img = img_binary.astype(float)
        img = (img * 255).astype("uint8")
        return img

    def preprocess_mask(self, mask: np.ndarray) -> np.ndarray:
        """
        Preprocesses a mask according to current settings.
        Args:
            mask (np.ndarray): Input mask (RGB or grayscale).
        Returns:
            np.ndarray: Preprocessed mask (uint8, grayscale).
        """
        s = self.settings
        if len(mask.shape) == 3:
            mask = ski.color.rgb2gray(mask)
        if s["invertmask"]:
            mask = 1.0 - mask
        if s["equalizemask"]:
            mask = ski.exposure.equalize_hist(mask)
        if s["blurmask"]:
            mask = ski.filters.gaussian(mask, sigma=s["sigmamask"])
        if s["cannymask"]:
            mask = ski.feature.canny(mask, sigma=s["sigmamask"])
            mask = mask.astype(float)
        if s["otsumask"]:
            # Convert to uint8 for threshold_otsu
            mask_uint8 = (mask * 255).astype("uint8")
            threshold = ski.filters.threshold_otsu(mask_uint8)
            mask = mask_uint8 > threshold
            mask = mask.astype(float)
        if s["manualthresholdmask"]:
            # Convert to uint8 for manual threshold
            mask_uint8 = (mask * 255).astype("uint8")
            mask = mask_uint8 > s["thresholdmask"]
            mask = mask.astype(float)
        if s["morphologymask"]:
            # Apply morphological operations
            mask_binary = (mask > 0.5).astype(bool) if mask.max() <= 1.0 else (mask > 127).astype(bool)
            morph_type = s["morphologytypemask"]
            strength = s["morphologystrengthmask"]
            kernel = ski.morphology.disk(strength)

            if morph_type == "erosion":
                mask_binary = ski.morphology.erosion(mask_binary, kernel)
            elif morph_type == "dilation":
                mask_binary = ski.morphology.dilation(mask_binary, kernel)
            elif morph_type == "opening":
                mask_binary = ski.morphology.opening(mask_binary, kernel)
            elif morph_type == "closing":
                mask_binary = ski.morphology.closing(mask_binary, kernel)

            mask = mask_binary.astype(float)
        mask = (mask * 255).astype("uint8")

        return mask


class AffineError(Exception):
    """
    Custom exception for affine registration errors.
    Includes a timestamp and error code for easier debugging.
    """

    def __init__(self, message: str, error_code: int) -> None:
        super().__init__(message)
        self.error_code: int = error_code
        self.message: str = message
        self.timestamp: str = datetime.now().strftime("%H:%M:%S.%f")
        self.message = f"{self.timestamp}: {self.message} (Affine error Code: {self.error_code})"

    def __str__(self) -> str:
        return self.message


class Affine_IO:
    """
    Handles loading and saving of images and GDS files for affine registration.
    """

    def __init__(self, path: str) -> None:
        self.path: str = path

    def load_and_save_gds(
        self,
        input_gds_path: str,
        output_image_path: Optional[str] = None,
        width: int = 1920,
        height: int = 1080,
    ) -> Tuple[np.ndarray, str]:
        """
        Loads a GDS file and saves it as a PNG image.
        Args:
            input_gds_path (str): Path to .gds file.
            output_image_path (str, optional): Where to save results. Defaults to None.
            width (int, optional): Image width.
            height (int, optional): Image height.
        Returns:
            Tuple[np.ndarray, str]: Loaded mask image (RGB), and filename (without extension).
        """
        filename = os.path.basename(input_gds_path)
        filename = filename.split(".")[0]
        if output_image_path is None:
            output_image_path = self.path + os.sep + "masks" + os.sep + filename + ".png"
        # Create a layout view
        view = lay.LayoutView(options=lay.LayoutView.LV_NoGrid)
        view.load_layout(input_gds_path, add_cellview=False)
        view.selection_size()
        view.zoom_fit()
        view.max_hier()
        h = view.viewport_height()
        w = view.viewport_width()
        aspect_ratio = w / h
        # scale the image to have the same aspect ratio and height 1080
        if aspect_ratio > 1:
            w = 1920
            h = int(1920 / aspect_ratio)
        else:
            h = 1080
            w = int(1080 * aspect_ratio)

        it = view.begin_layers()
        # colorlist, encoded as 32bit values in the following way:
        # The color is a 32bit value encoding the blue value in the lower 8 bits, the green value in the next 8 bits and the red value in the 8 bits above that.
        """             
        colorlist = [
            0xFF0000,  # Red
            0x00FF00,  # Green
            0x0000FF,  # Blue
        ]

        """
        # color_idx = 0
        while not it.at_end():
            lp = it.current()
            new_layer = lp.dup()
            new_layer.visible = True
            new_layer.clear_dither_pattern()
            """
            try:
                new_layer.fill_color = colorlist[color_idx % len(colorlist)]
                color_idx += 1
            except IndexError:
                pass
            """
            view.set_layer_properties(it, new_layer)
            it.next()
        view.set_config("grid-show-ruler", "false")
        view.commit_config()
        view.set_config("background-color", "#00000000")
        view.set_config("grid-visible", "false")
        view.save_image(output_image_path, width=w, height=h)
        # view.save_screenshot(output_image_path.replace(".png", "_screenshot.png"))
        internal_mask = cv.imread(output_image_path)
        internal_mask = cv.cvtColor(internal_mask, cv.COLOR_BGR2RGB)
        return internal_mask, filename

    def load_image(self, path: str) -> Tuple[np.ndarray, str]:
        """
        Loads a mask image from the specified path.
        Args:
            path (str): Path to the image file.
        Returns:
            Tuple[np.ndarray, str]: Loaded image (RGB), and filename (without extension).
        Raises:
            AffineError: If the image cannot be loaded.
        """
        img = cv.imread(path)
        filename = os.path.basename(path)
        filename = filename.split(".")[0]
        if img is None:
            raise AffineError(f"Could not load image from {path}", 5)
        img = cv.cvtColor(img, cv.COLOR_BGR2RGB)
        return img, filename


class Affine:
    """
    Calculates the affine transformation between two images using feature keypoints and descriptors.
    Supports multiple backends: SIFT, ORB, and . Assumes the images are grayscale or RGB (converted internally).
    Usage:
        - Create an Affine object.
        - Load the mask image using update_internal_mask().
        - Call try_match() with the input image.
        - If the transformation is found, access the transformation matrix using the A attribute.
        - Use coords() to get the transformed coordinates of a point.
    """

    path: str
    result: Dict[str, Any]
    A: Optional[np.ndarray]
    internal_img: Optional[np.ndarray]
    internal_mask: Optional[np.ndarray]
    MIN_MATCHES: int
    preprocessor: Preprocessor
    io: Affine_IO
    ratio_test: float
    residual_threshold: int
    cross_check: bool
    backend: str

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """
        Initializes an instance of Affine. Optionally takes a settings dict.
        Args:
            settings (dict, optional): Settings for algorithm and preprocessing.
        """
        self.path = os.path.dirname(__file__) + os.path.sep
        self.result = dict()
        self.A = None  # Affine transformation matrix
        self.internal_img = None  # Internal image
        self.internal_mask = None  # Internal mask
        self.MIN_MATCHES = 4
        self.preprocessor = Preprocessor()
        self.io = Affine_IO(self.path)
        self.ratio_test = 0.80
        self.residual_threshold = 10
        self.cross_check = True
        self.backend = "SIFT"  # Default backend
        if settings is not None:
            self.update_settings(settings)

    def update_settings(self, settings: Dict[str, Any]) -> None:
        """
        Update algorithmic and preprocessing settings from a dictionary.
        Accepts keys: ratiotest, residualthreshold, crosscheck, and preprocessing keys.
        Args:
            settings (dict): Settings dictionary.
        """
        if "ratiotest" in settings:
            self.ratio_test = float(settings["ratiotest"])
        if "residualthreshold" in settings:
            self.residual_threshold = int(settings["residualthreshold"])
        if "crosscheck" in settings:
            val = settings["crosscheck"]
            if isinstance(val, str):
                self.cross_check = val.lower() == "true"
            else:
                self.cross_check = bool(val)
        if "backend" in settings:
            self.backend = settings["backend"]
        self.preprocessor.update_settings(settings)

    def _create_feature_detector(self):
        """
        Creates the appropriate feature detector based on the selected backend.
        Returns:
            Feature detector instance.
        Raises:
            AffineError: If unsupported backend is specified.
        """
        if self.backend == "SIFT":
            return SIFT()
        elif self.backend == "ORB":
            return ORB(n_keypoints=1000)

        else:
            raise AffineError(f"Unsupported backend: {self.backend}", 4)

    def try_match(self, img: np.ndarray) -> bool:
        """
        Attempts to find the affine transformation between the input image and
        mask using feature keypoints and descriptors (SIFT, ORB,).
        Args:
            img (np.ndarray): Input image to match with the mask.
        Returns:
            bool: True if transformation is found, raises AffineError otherwise.
        Raises:
            AffineError: If no image/mask is loaded, or not enough matches, or feature detection fails.
        """
        cross_check = self.cross_check
        residual_threshold = self.residual_threshold
        max_ratio = self.ratio_test
        mask = self.internal_mask
        if img is None:
            raise AffineError("No image provided.", 1)
        if mask is None:
            raise AffineError("No mask loaded.", 2)
        img = self.preprocessor.preprocess_img(img)
        mask = self.preprocessor.preprocess_mask(mask)
        self.result["img"] = img
        self.result["mask"] = mask
        try:
            detector = self._create_feature_detector()
            detector.detect_and_extract(img)
            kp_img, desc_img = detector.keypoints, detector.descriptors
            detector.detect_and_extract(mask)
            kp_mask, desc_mask = detector.keypoints, detector.descriptors
        except RuntimeError as e:
            raise AffineError(f"Runtime error during {self.backend} detection: {e}", 3) from e

        self.result["kp1"] = kp_mask
        self.result["kp2"] = kp_img
        print("Keypoints in mask:", len(kp_mask))
        print("Keypoints in image:", len(kp_img))
        matches = match_descriptors(desc_mask, desc_img, max_ratio=max_ratio, cross_check=cross_check)
        print("Matches found:", len(matches))
        if len(matches) < self.MIN_MATCHES:
            raise AffineError(f"Not enough matches found: {len(matches)} < {self.MIN_MATCHES}", 3)
        if kp_mask is None or kp_img is None:
            raise AffineError("No keypoints found in either image or mask.", 3)
        src = kp_mask[matches[:, 0]][:, ::-1].astype(np.float32)  # mask keypoints masked with matches
        dst = kp_img[matches[:, 1]][:, ::-1].astype(np.float32)  # image keypoints masked with matches

        print("Source points (mask) matched: ", len(src))
        print("Destination points (image) matched:", len(dst))
        print("Example mask point: ", src[0])
        model, inliers = self.get_transformation(src, dst, residual_threshold=residual_threshold)
        self.A = model.params
        matches = matches[inliers]
        self.result["img"] = img
        self.result["mask"] = mask
        self.result["kp1"] = kp_mask
        self.result["kp2"] = kp_img
        self.result["matches"] = matches
        self.result["transform"] = model
        return True

    def get_transformation(
        self, src: np.ndarray, dst: np.ndarray, residual_threshold: int = 10
    ) -> Tuple[Any, np.ndarray]:
        """
        Estimate the affine transformation using RANSAC.
        Args:
            src (np.ndarray): Source points (N, 2).
            dst (np.ndarray): Destination points (N, 2).
            residual_threshold (int): RANSAC residual threshold.
        Returns:
            Tuple[SimilarityTransform, np.ndarray]: Model and inlier mask.
        Raises:
            AffineError: If RANSAC fails to find a transform.
        """

        model, inliers = ski.measure.ransac(
            (src, dst),
            ski.transform.SimilarityTransform,
            min_samples=4,
            residual_threshold=residual_threshold,
            max_trials=5000,
        )
        if inliers is None:
            raise AffineError("Ransac filtered out all points", 3)

        inliers = np.asarray(inliers)
        return model, inliers

    def manual_transform(
        self,
        src: np.ndarray,
        dst: np.ndarray,
        img: np.ndarray,
        mask: np.ndarray,
    ) -> None:
        """
        Apply an affine transform manually, given points from the mask and image respectively.
        Args:
            src (np.ndarray): Points from the mask (N, 2).
            dst (np.ndarray): Corresponding points from the image (N, 2).
            img (np.ndarray): Image array.
            mask (np.ndarray): Mask array.
        Raises:
            AffineError: If transformation fails.
        """
        try:
            src = np.array(src, dtype=np.float32)
            dst = np.array(dst, dtype=np.float32)
            model, inliers = self.get_transformation(
                src,
                dst,
            )
            self.A = model.params
            self.result["img"] = img
            self.result["mask"] = mask
            self.result["kp1"] = dst
            self.result["kp2"] = src
            self.result["matches"] = np.array(
                [[i, i] for i in range(len(src))]  # dummy matches to retain the structure
            )
        except Exception as e:
            raise AffineError(f"Error during manual transformation: {e}", 3) from e

    def coords(self, point: Tuple[float, float]) -> Tuple[float, float]:
        """
        Transforms a point from the mask to the corresponding point on the image using the affine transformation.
        Args:
            point (Tuple[float, float]): (x, y) coordinates of the point on the mask.
        Returns:
            Tuple[float, float]: (x, y) coordinates of the transformed point on the image.
        Raises:
            AffineError: If no affine transformation has been found.
        """
        if self.A is None:
            raise AffineError("No affine transformation found.", 4)
        point_homogeneous = np.array([point[0], point[1], 1.0])  # convert to homogeneous coordinates
        transformed = self.A @ point_homogeneous  # operate transform on homogeneous coordinates
        cartesian = transformed[:2] / transformed[2]  # back to cartesian reference frame
        return float(cartesian[0]), float(cartesian[1])

    def update_internal_mask(self, path: str) -> np.ndarray:
        """
        Loads and sets the internal mask from a file path (image or GDS).
        Args:
            path (str): Path to mask image or GDS file.
        Returns:
            np.ndarray: Loaded mask image.
        """
        try:
            if path.endswith(".gds"):
                mask, filename = self.io.load_and_save_gds(path)
            else:
                mask, filename = self.io.load_image(path)
            self.mask_filename = filename
            self.mask_path = path
            self.internal_mask = mask
            self.result.clear()
            return mask
        except Exception as e:
            raise AffineError(f"Error loading mask from {path}: {e}", 2) from e

    def center_on_component(self, x: int, y: int) -> Tuple[int, int]:
        """
        Finds the centroid of a connected component in the mask image based on the color at (x, y).
        Args:
            x (int): X coordinate in the mask image.
            y (int): Y coordinate in the mask image.
        Returns:
            Tuple[int, int]: Centered coordinates (x, y) of the selected component.
        Raises:
            AffineError: If no internal mask is loaded.
        """
        if self.internal_mask is None:
            raise AffineError("No internal mask available loaded.", 2)
        mask = self.internal_mask
        if mask.ndim != 3 or mask.shape[2] != 3:
            mask = ski.color.gray2rgb(mask)
        target_color = mask[y, x]
        color_match = np.all(mask == target_color, axis=-1)
        labeled_mask = ski.measure.label(color_match, connectivity=2)
        labeled_mask = np.asarray(labeled_mask)
        label_clicked: int = int(labeled_mask[y, x])
        props = ski.measure.regionprops(labeled_mask)
        for region in props:
            if region.label == label_clicked:
                cy, cx = region.centroid
                return (int(cx), int(cy))
        return (x, y)  # return original coords if no region found
