export type FunctionConfigProps = Record<string, string>;
export type FunctionConfigs = Record<string, FunctionConfigProps[]>;

export type ThresholdMethod = "PROTECTED" | "EXPOSED";

export interface ThresholdConfig {
    enabled: boolean;
    threshold: number;
    thresholdMethod: ThresholdMethod
}