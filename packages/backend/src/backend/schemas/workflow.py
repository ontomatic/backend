from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ItemKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Positive = Annotated[float, Field(gt=0, le=1_000_000_000, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, le=1_000_000_000, allow_inf_nan=False)]
DocumentKind = Literal[
  'product_detail',
  'bom_transfer',
  'incoming_inspection',
  'production_plan',
  'work_instruction_module1',
  'inspection_module1',
  'work_instruction_lens',
  'work_instruction_body',
  'inspection_module2',
  'work_instruction_final',
  'inspection_final',
]


class Input(BaseModel):
  model_config = ConfigDict(extra='forbid')


class Evidence(Input):
  document_id: Text
  page: int | None = Field(default=None, ge=1)
  block_index: int | None = Field(default=None, ge=1)
  row: str = Field(min_length=1, max_length=200)
  original_field: str = Field(default='', max_length=200)
  original_value: str = Field(default='', max_length=2000)
  original_unit: str = Field(default='', max_length=30)


class Attribute(Input):
  field: Text
  value: str | float
  unit: str = Field(default='', max_length=30)
  required: bool = True
  confirmed: bool = False
  source: Evidence | None = None


class Item(Input):
  key: ItemKey
  code: str = Field(default='', max_length=80)
  name: Text
  kind: Literal['product', 'assembly', 'component', 'material']
  version: int = Field(default=1, ge=1)
  unit: Text = '개'
  aliases: list[Text] = Field(default_factory=list, max_length=100)
  confirmed: bool = False
  attributes: list[Attribute] = Field(default_factory=list, max_length=300)


class Relation(Input):
  parent: ItemKey
  child: ItemKey
  quantity: Positive
  condition: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
  confirmed: bool = False
  source: Evidence | None = None


class Graph(Input):
  root: ItemKey
  items: list[Item] = Field(min_length=1, max_length=500)
  relations: list[Relation] = Field(default_factory=list, max_length=2000)


class SpecificationIn(Input):
  code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
  name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
  product_type: Literal['digital', 'telephoto', 'film', 'polaroid']
  graph: Graph
  previous_id: str | None = None
  reason: str = Field(default='', max_length=2000)


class DraftIn(Input):
  revision: int = Field(ge=1)
  graph: Graph


class RevisionIn(Input):
  revision: int = Field(ge=1)


class ItemImportIn(RevisionIn):
  source_specification_id: Text
  item_key: ItemKey


class JobIn(Input):
  specification_id: Text
  name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
  quantity: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]


class DocumentIn(Input):
  file_id: int = Field(gt=0)
  kind: DocumentKind | Literal['auto']
  specification_id: str | None = None
  job_id: str | None = None
  target_ids: list[Text] = Field(default_factory=list, max_length=500)
  round: int = Field(default=1, ge=1)
  plan_version: int = Field(default=0, ge=0)


class ExtractionIn(Input):
  graph_candidate: bool = False


class PlanLine(Input):
  target_id: Text
  process: Text
  track: Text
  quantity: Positive
  unit: Text
  duration: Positive
  duration_unit: Literal['minute', 'hour']
  time_basis: Literal['per_item', 'batch', 'setup']
  resource: Text
  start: datetime
  end: datetime
  predecessors: list[Text] = Field(default_factory=list, max_length=500)
  sources: list[Evidence] = Field(min_length=1, max_length=100)


class PlanIn(RevisionIn):
  quantity: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]
  reason: Reason
  lines: list[PlanLine] = Field(min_length=1, max_length=500)
  acknowledged_warnings: bool = False
  confirmed: bool = False


class ScheduleEntry(Input):
  kind: Literal['summary', 'operation']
  code: str = Field(default='', max_length=200)
  process: Text
  track: str = Field(default='', max_length=200)
  quantity: str = Field(default='', max_length=200)
  start: date
  end: date
  working_days: int | None = Field(default=None, gt=0, le=100000)
  resource: str = Field(default='', max_length=200)
  owner: str = Field(default='', max_length=200)
  assistants: str = Field(default='', max_length=1000)
  headcount: int | None = Field(default=None, gt=0, le=100000)
  predecessors: list[Text] = Field(default_factory=list, max_length=500)
  note: str = Field(default='', max_length=2000)
  sources: list[Evidence] = Field(min_length=1, max_length=100)


class SchedulePlanIn(RevisionIn):
  quantity: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]
  reason: Reason
  schedule: list[ScheduleEntry] = Field(min_length=1, max_length=500)
  acknowledged_warnings: bool = False
  confirmed: bool = False


class TargetIn(RevisionIn):
  target_id: Text


class CompletionIn(TargetIn):
  quantity: Positive
  unit: Text
  confirmed: bool = False
  sources: list[Evidence] = Field(default_factory=list, max_length=100)


class InspectionIn(TargetIn):
  result: Literal['pass', 'fail']
  criterion: Reason
  standard: Text
  measured_value: Text
  unit: str = Field(default='', max_length=30)
  grade: str = Field(default='', max_length=100)
  sources: list[Evidence] = Field(default_factory=list, max_length=100)
  confirmed: bool = False
  cause: Literal['physical', 'specification', 'evidence'] | None = None
  reason: str = Field(default='', max_length=2000)
  good_quantity: Nonnegative | None = None
  defect_quantity: Nonnegative | None = None


class ReworkIn(TargetIn):
  cause: Literal['physical', 'specification', 'evidence']
  reason: Reason
  specification_id: str | None = None
  document_ids: list[Text] = Field(default_factory=list, max_length=100)


class RagIn(Input):
  question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
  specification_id: Text
  job_id: str | None = None
