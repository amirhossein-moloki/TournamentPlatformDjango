import clamd
import magic
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadhandler import TemporaryFileUploadHandler


class SafeFileUploadHandler(TemporaryFileUploadHandler):
    """
    Custom file upload handler to validate file type and size.
    """

    def __init__(self, request=None):
        super().__init__(request)
        self.max_size = 1024 * 1024 * 5  # 5 MB
        self.allowed_content_types = ["image/jpeg", "image/png"]

    def receive_data_chunk(self, raw_data, start):
        if self.file_size > self.max_size:
            raise ValidationError(
                f"File size exceeds the limit of {self.max_size} bytes."
            )
        return super().receive_data_chunk(raw_data, start)

    def file_complete(self, file_size):
        self.file.seek(0)
        mime_type = magic.from_buffer(self.file.read(1024), mime=True)
        self.file.seek(0)

        if mime_type not in self.allowed_content_types:
            raise ValidationError(f"Invalid content type: {mime_type}")

        # Protect against "billion laughs" attack
        self.file.seek(0)
        try:
            with Image.open(self.file) as img:
                if img.width * img.height > 10000 * 10000:
                    raise ValidationError("Image is too large.")
        except IOError:
            raise ValidationError("Invalid image file.")
        finally:
            self.file.seek(0)

        try:
            cd = clamd.ClamdUnixSocket()
            cd.ping()
        except clamd.ConnectionError:
            # If the clamav daemon is not running, we can't scan the file.
            # Depending on the security requirements, you might want to
            # deny the upload or log the error and continue.
            pass
        else:
            self.file.seek(0)
            result = cd.instream(self.file)
            self.file.seek(0)
            if result and result["stream"][0] == "FOUND":
                raise ValidationError("Malware detected in the uploaded file.")

        return super().file_complete(file_size)
