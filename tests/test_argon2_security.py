"""
Test Argon2 password hashing security
اختبار أمان تشفير كلمات المرور باستخدام Argon2
"""

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from secret_admin_panel import SecretAdminPanel
from unittest.mock import (
    MagicMock,
)  # --- التعديل هنا: استيراد الأداة اللازمة للاختبار ---


class TestArgon2Security:
    """Test Argon2 password hashing security"""

    def test_argon2_password_hashing(self):
        """Test that Argon2 properly hashes passwords"""
        ph = PasswordHasher()
        password = "test_password_123"

        # Hash the password
        hashed = ph.hash(password)

        # Verify the hash is different from original
        assert hashed != password
        assert len(hashed) > len(password)

        # Verify the password can be verified
        assert ph.verify(hashed, password) is True

        # Verify wrong password fails
        with pytest.raises(VerifyMismatchError):
            ph.verify(hashed, "wrong_password")

    def test_secret_admin_panel_password_hashing(self):
        """Test SecretAdminPanel password hashing with Argon2"""
        # --- التعديل هنا: إنشاء كائن وهمي وتمريره لحل خطأ TypeError ---
        mock_data_store = MagicMock()
        panel = SecretAdminPanel(data_store=mock_data_store)

        # --- التعديل هنا: تصحيح منطق الاختبار ---
        test_password = "admin_secret_123"

        # 1. نقوم بتشفير كلمة مرور جديدة
        hashed = panel.auth.ph.hash(test_password)

        # 2. نقوم بتعيين كلمة المرور المشفرة الجديدة للكائن الذي نختبره
        panel.auth.encrypted_pass = hashed

        # 3. الآن نتأكد من أن عملية التحقق تعمل على الـ hash الصحيح
        assert panel.auth.verify(test_password) is True
        assert panel.auth.verify("wrong_password") is False

    def test_argon2_salt_uniqueness(self):
        """Test that Argon2 generates unique salts for each password"""
        ph = PasswordHasher()
        password = "same_password"

        # Hash the same password multiple times
        hash1 = ph.hash(password)
        hash2 = ph.hash(password)
        hash3 = ph.hash(password)

        # All hashes should be different due to unique salts
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

        # But all should verify correctly
        assert ph.verify(hash1, password) is True
        assert ph.verify(hash2, password) is True
        assert ph.verify(hash3, password) is True

    def test_argon2_brute_force_resistance(self):
        """Test that Argon2 is resistant to brute force attacks"""
        ph = PasswordHasher()
        password = "weak_password"

        # Hash with default settings (should be slow enough)
        hashed = ph.hash(password)

        # Verify it takes reasonable time to verify
        import time

        start_time = time.time()
        result = ph.verify(hashed, password)
        end_time = time.time()

        assert result is True
        # Verification should take at least 10ms (but not too long)
        assert 0.01 <= (end_time - start_time) <= 1.0

    def test_invalid_hash_handling(self):
        """Test handling of invalid or corrupted hashes"""
        # --- التعديل هنا: إنشاء كائن وهمي وتمريره لحل خطأ TypeError ---
        mock_data_store = MagicMock()
        panel = SecretAdminPanel(data_store=mock_data_store)

        # --- التعديل هنا: تصحيح منطق الاختبار ---
        # نتأكد من أن دالة verify تعيد False بأمان عند التعامل مع hash تالف

        # Test with invalid hash
        panel.auth.encrypted_pass = "invalid_hash"
        assert panel.auth.verify("any_password") is False

        # Test with empty hash
        panel.auth.encrypted_pass = ""
        assert panel.auth.verify("any_password") is False

        # Test with None hash
        panel.auth.encrypted_pass = None
        assert panel.auth.verify("any_password") is False
