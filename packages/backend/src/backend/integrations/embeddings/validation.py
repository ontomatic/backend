from math import isfinite


def validate_vectors(vectors: object, expected: int) -> list[list[float]]:
  if not isinstance(vectors, list) or len(vectors) != expected:
    raise RuntimeError('Invalid embedding response')

  for vector in vectors:
    if (
      not isinstance(vector, list)
      or not vector
      or len(vector) != len(vectors[0])
      or any(type(value) not in (int, float) or not isfinite(value) for value in vector)
    ):
      raise RuntimeError('Invalid embedding response')

  return vectors
