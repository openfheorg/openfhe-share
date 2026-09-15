export interface ObservationComponent {
  code: {
    coding: { code: string }[];
  };
  valueQuantity?: {
    value: number;
  };
  valueCodeableConcept?: {
    coding: { code: string; display: string }[];
  };
}