export interface Medication {
    id: string;
    subjectReference: string;
    medicationCodeableConcept?: {
        coding: { code: string; display: string; system: string }[];
    };
    status: string;
}