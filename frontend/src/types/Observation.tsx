import { ObservationComponent } from "./ObservationComponent";

export interface Observation {
  id: string;
  subjectReference: string;
  components: ObservationComponent[];

  code?: {
    coding?: { system?: string; code?: string; display?: string }[];
  };
  interpretation?: {
    coding?: { system?: string; code?: string; display?: string }[];
  }[];
}