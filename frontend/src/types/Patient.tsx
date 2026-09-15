export interface Patient {
  id: string;
  family: string;
  given: string;
  gender: string;
  birthDate: string;
  fullUrl: string;
  deceasedDateTime?: string;
  medication?: string;
}