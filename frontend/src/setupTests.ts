// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import { TextDecoder, TextEncoder } from 'util';

// react-scripts/Jest runs under jsdom, which does not provide the Encoding API
// in every supported Node version. pako and LaunchPayload rely on these browser
// globals, so provide the Node equivalents for the test environment only.
Object.assign(globalThis, {
  TextDecoder,
  TextEncoder,
});
