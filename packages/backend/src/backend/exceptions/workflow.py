from backend.exceptions.base import AppException


class WorkflowError(AppException):
  status_code = 422
  code = 'WORKFLOW_VALIDATION'


class WorkflowConflict(WorkflowError):
  status_code = 409
  code = 'WORKFLOW_CONFLICT'


class WorkflowNotFound(WorkflowError):
  status_code = 404
  code = 'WORKFLOW_NOT_FOUND'


class WorkflowPermission(WorkflowError):
  status_code = 403
  code = 'WORKFLOW_PERMISSION'
