import magic

ALLOWED_IMG_MIME = {'image/jpeg', 'image/png'}
ALLOWED_DOC_MIME = ALLOWED_IMG_MIME | {'application/pdf'}
MAX_IMG = 5 * 1024 * 1024
MAX_DOC = 50 * 1024 * 1024


class UploadValidationError(ValueError):
    pass


def validate_upload(file, max_size=MAX_IMG, allowed=ALLOWED_IMG_MIME):
    if file.size > max_size:
        raise UploadValidationError(f"Max {max_size // 1024 // 1024}MB.")
    mime = magic.from_buffer(file.read(2048), mime=True)
    file.seek(0)
    if mime not in allowed:
        raise UploadValidationError("File type not allowed.")
