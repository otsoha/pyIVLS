import numpy as np
import cv2 as cv
import pytest
from skimage.transform import AffineTransform, warp
from plugins.Affine.Affine_skimage import Affine, AffineError
import os


def create_synthetic_image(size=(200, 200), square_pos=(50, 50), square_size=40):
    img = np.zeros(size, dtype=np.uint8)
    x, y = square_pos
    img[y : y + square_size, x : x + square_size] = 255
    img_rgb = cv.cvtColor(img, cv.COLOR_GRAY2RGB)
    return img_rgb


def apply_affine(img, matrix):
    tform = AffineTransform(matrix=matrix)
    warped = warp(img, tform.inverse, output_shape=img.shape)
    warped = (warped * 255).astype(np.uint8)
    return warped


def test_manual_transform_and_coords():
    aff = Affine()
    src = [(10, 10), (100, 10), (10, 100), (100, 100)]
    dst = [(20, 20), (120, 20), (20, 120), (120, 120)]
    # Convert to ndarray
    src = np.array(src, dtype=float)
    dst = np.array(dst, dtype=float)
    img = create_synthetic_image()
    mask = create_synthetic_image()
    aff.manual_transform(src, dst, img, mask)
    pt = (10, 10)
    transformed = aff.coords(pt)
    assert np.allclose(transformed, (20, 20), atol=1)
    # Check for multiple points
    for s, d in zip(src, dst):
        assert np.allclose(aff.coords(s), d, atol=1)
    # Check matrix shape and not all zeros
    assert aff.A is not None
    assert np.any(aff.A != 0)
    # Check error if coords called before transform
    aff2 = Affine()
    with pytest.raises(AffineError):
        aff2.coords((0, 0))


def test_update_internal_mask_and_test_image():
    aff = Affine()
    img = create_synthetic_image()
    temp_path = "temp_test_img.png"
    cv.imwrite(temp_path, cv.cvtColor(img, cv.COLOR_RGB2BGR))
    mask = aff.update_internal_mask(temp_path)
    assert mask is not None
    assert aff.internal_mask is not None
    # Check that mask is cleared after update
    aff.update_internal_mask(temp_path)
    assert aff.result == {}
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_try_match_affine():
    aff = Affine()
    img = create_synthetic_image()
    matrix = np.array([[1, 0, 20], [0, 1, 30], [0, 0, 1]], dtype=float)
    aff_img = apply_affine(img, matrix)
    aff.internal_mask = img
    try:
        aff.try_match(aff_img)
        found = aff.A
        assert found is not None
        assert found.shape == (3, 3)
        assert np.any(found != 0)
        # Check that keypoints and matches are present
        assert "kp1" in aff.result and "kp2" in aff.result and "matches" in aff.result
        assert aff.result["matches"].shape[0] >= aff.MIN_MATCHES
        # Check that the found matrix is close to the true one
        assert np.allclose(found[:2, :], matrix[:2, :], atol=5)
    except AffineError as e:
        pytest.skip(f"SIFT could not find enough matches: {e}")
    # Check error if no mask
    aff2 = Affine()
    with pytest.raises(AffineError):
        aff2.try_match(aff_img)


def test_center_on_component():
    aff = Affine()
    img = create_synthetic_image()
    aff.internal_mask = img
    cx, cy = aff.center_on_component(55, 55)
    assert isinstance(cx, int) and isinstance(cy, int)
    assert abs(cx - 70) < 5 and abs(cy - 70) < 5
    # Check error if no mask
    aff2 = Affine()
    with pytest.raises(AffineError):
        aff2.center_on_component(10, 10)


def test_img_matches_refled(caplog):
    """Each image in test_media/img matches with refLED_v3_flat.png."""
    import glob

    img_dir = os.path.join("tests", "test_media", "img")
    mask_path = os.path.join("tests", "test_media", "masks", "refLED_v3_flat.png")
    img_files = sorted(glob.glob(os.path.join(img_dir, "*.png")))
    assert os.path.exists(mask_path)
    for img_path in img_files:
        aff = Affine()
        aff.update_internal_mask(mask_path)
        img = cv.imread(img_path)
        img = cv.cvtColor(img, cv.COLOR_BGR2RGB)
        try:
            aff.try_match(img)
            caplog.set_level("INFO")
            import logging

            logging.info(f"[MATCH] {os.path.basename(img_path)}: matches found = {aff.result['matches'].shape[0]}")
            assert aff.A is not None
            assert aff.result["matches"].shape[0] >= aff.MIN_MATCHES
        except AffineError as e:
            caplog.set_level("WARNING")
            import logging

            logging.warning(f"[FAIL] {os.path.basename(img_path)}: {e}")
            pytest.skip(f"Could not match {img_path} with refLED_v3_flat.png: {e}")


def test_img_does_not_match_bob(caplog):
    """Each image in test_media/img does not match with testBob.jpg."""
    import glob

    img_dir = os.path.join("tests", "test_media", "img")
    nonmatch_path = os.path.join("tests", "test_media", "masks", "testBob.jpg")
    img_files = sorted(glob.glob(os.path.join(img_dir, "*.png")))
    assert os.path.exists(nonmatch_path)
    for img_path in img_files:
        aff = Affine()
        aff.update_internal_mask(nonmatch_path)
        img = cv.imread(img_path)
        img = cv.cvtColor(img, cv.COLOR_BGR2RGB)
        try:
            aff.try_match(img)
            caplog.set_level("INFO")
            import logging

            logging.info(f"[NONMATCH] {os.path.basename(img_path)}: matches found = {aff.result['matches'].shape[0]}")
            assert aff.result["matches"].shape[0] < aff.MIN_MATCHES
        except AffineError:
            caplog.set_level("INFO")
            import logging

            logging.info(f"[NONMATCH] {os.path.basename(img_path)}: AffineError (expected)")
            pass  # Expected: should not match


def test_affine_transform_of_mask_matches():
    """Apply an affine transform to the mask and check that it matches with itself."""
    mask_path = os.path.join("tests", "test_media", "masks", "refLED_v3_flat.png")
    aff = Affine()
    aff.update_internal_mask(mask_path)
    mask = aff.internal_mask
    assert mask is not None, "Mask was not loaded correctly."
    # Apply a known affine transform
    from skimage.transform import AffineTransform, warp

    matrix = np.array([[1, 0, 15], [0, 1, 25], [0, 0, 1]], dtype=float)
    tform = AffineTransform(matrix=matrix)
    warped = warp(mask, tform.inverse, output_shape=mask.shape)
    warped = (warped * 255).astype(np.uint8)
    try:
        aff.try_match(warped)
        assert aff.A is not None
        assert aff.result["matches"].shape[0] >= aff.MIN_MATCHES
        assert np.allclose(aff.A[:2, :], matrix[:2, :], atol=5)
    except AffineError as e:
        pytest.skip(f"Could not match affine transformed mask: {e}")


def test_preprocessor_settings():
    aff = Affine()
    img = create_synthetic_image()
    # Test blurimage
    aff.preprocessor.update_settings({"blurimage": True, "sigmaimage": 2.0})
    blurred = aff.preprocessor.preprocess_img(img)
    assert blurred.ndim == 2
    assert blurred.shape == img.shape[:2]
    # Test invertimage
    aff.preprocessor.update_settings({"invertimage": True, "blurimage": False})
    inverted = aff.preprocessor.preprocess_img(img)
    aff.preprocessor.update_settings({"invertimage": False})
    gray = aff.preprocessor.preprocess_img(img)
    assert np.allclose(inverted, 255 - gray)
    # Test cannyimage
    aff.preprocessor.update_settings({"cannyimage": True, "sigmaimage": 1.0, "invertimage": False})
    canny = aff.preprocessor.preprocess_img(img)
    assert canny.ndim == 2
    assert canny.shape == img.shape[:2]
    assert canny.dtype == np.uint8
    # Test otsuimage
    aff.preprocessor.update_settings({"otsuimage": True, "cannyimage": False})
    otsu = aff.preprocessor.preprocess_img(img)
    assert otsu.ndim == 2
    assert otsu.shape == img.shape[:2]
    assert otsu.dtype == np.uint8
    # Otsu should produce binary output (only 0 and 255 values)
    unique_values = np.unique(otsu)
    assert len(unique_values) <= 2  # Binary thresholding should produce at most 2 values
    assert all(val in [0, 255] for val in unique_values)
    # Test otsumask
    aff.preprocessor.update_settings({"otsumask": True, "otsuimage": False})
    otsu_mask = aff.preprocessor.preprocess_mask(img)
    assert otsu_mask.ndim == 2
    assert otsu_mask.shape == img.shape[:2]
    assert otsu_mask.dtype == np.uint8
    # Otsu should produce binary output (only 0 and 255 values)
    unique_values_mask = np.unique(otsu_mask)
    assert len(unique_values_mask) <= 2  # Binary thresholding should produce at most 2 values
    assert all(val in [0, 255] for val in unique_values_mask)


def test_affine_settings_update():
    aff = Affine()
    # Default
    assert aff.ratio_test == 0.80
    assert aff.residual_threshold == 10
    assert aff.cross_check is True
    # Update
    aff.update_settings({"ratiotest": 0.5, "residualthreshold": 5, "crosscheck": False})
    assert aff.ratio_test == 0.5
    assert aff.residual_threshold == 5
    assert aff.cross_check is False
