class AppException(Exception):
  status_code = 500
  code = 'INTERNAL_SERVER_ERROR'
  message = '서버 오류가 발생했습니다. 잠시 후 재시도 해주세요.'

  def __init__(self, message: str | None = None):
    self.message = message if message is not None else type(self).message
    super().__init__(self.message)
