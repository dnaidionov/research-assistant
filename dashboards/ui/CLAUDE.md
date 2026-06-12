# Code Review Checklist

I will use this checklist to evaluate all code changes.

### 1. Architecture & Design
- [ ] **State Management**: Is local state minimized and global state handled via shared hooks/context when appropriate?
- [ ] **Prop Drilling**: Are we passing props through unnecessary layers? Consider React Context or dedicated hooks.
- [ ] **Component Composition**: Are components modular and reusable? Avoid monolithic components.

### 2. API Interaction
- [ ] **Endpoint Usage**: Are all API calls correctly typed and validated? (Where applicable)
- [ ] **Error Handling**: Is there proper `try/catch` or `.catch()`? Do errors surface gracefully (e.g., toast notifications)?
- [ ] **Loading States**: Are loading states handled for all async operations? (e.g., showing skeleton loaders or spinners).
- [ ] **Data Hydration**: Does the component handle initial loading states (empty data) gracefully before hydration?.
- [ ] **Optimistic Updates**: If needed, are optimistic UI updates implemented to improve perceived performance?

### 3. Performance
- [ ] **Memoization**: Are expensive calculations or component renders optimized using `useMemo`, `useCallback`, or `React.memo`?
- [ ] **List Rendering**: Are `key` props used and stable for all items in lists?
- [ ] **Lazy Loading**: Are large components or data fetches lazy-loaded when appropriate (e.g., `React.lazy`, dynamic imports)?
- [ ] **Debounce/Throttle**: Are expensive event handlers (e.g., `onScroll`, `onResize`, `onType`) debounced/throttled?

### 4. TypeScript & Typing
- [ ] **Strict Mode**: Is `strict: true` enabled in `tsconfig.json`?
- [ ] **Type Safety**: Are types explicitly defined for component props, state, and API responses?
- [ ] **Over-reliance on `any`**: Minimize the use of `any`; prefer `unknown` or specific interfaces when unsure.
- [ ] **Type Inference**: Is TypeScript able to infer types where possible without explicit annotation?

### 5. UI/UX & Accessibility (A11y)
- [ ] **Contrast**: Is there sufficient color contrast between text and background?
- [ ] **Keyboard Navigation**: Can the component be fully operated using a keyboard?
- [ ] **Focus Management**: Is focus managed correctly, especially after state changes or modal openings?
- [ ] **Semantic HTML**: Are appropriate HTML5 elements used (e.g., `<button>` for actions, `<a>` for navigation)?
- [ ] **ARIA Labels**: Are ARIA labels used for interactive elements without visible text content?

### 6. Testing
- [ ] **Unit Tests**: Are unit tests written for new components or complex logic (e.g., using Vitest/Jest)?
- [ ] **Integration Tests**: Are integration tests used for flows involving multiple components?
- [ ] **Test Coverage**: Do tests cover edge cases and error states?

### 7. Security
- [ ] **XSS Protection**: Is user-generated content properly sanitized (e.g., using `react-markdown` with sanitization)?
- [ ] **Secret Management**: Are API keys or secrets kept out of the codebase (use `.env` files)?

### 8. Code Style & Maintainability
- [ ] **Readability**: Is the code clean, well-formatted, and easy to understand?
- [ ] **Naming**: Are variable, function, and component names descriptive?
- [ ] **Comments**: Are complex logic sections documented with meaningful comments?
- [ ] **DRY Principle**: Is there unnecessary code duplication (Don't Repeat Yourself)?
- [ ] **File Organization**: Are components and hooks organized logically within the project structure?

### 9. Performance Optimization
- [ ] **Bundle Size**: Are there large, unnecessary dependencies that could be optimized or tree-shaken?
- [ ] **Image Optimization**: Are images properly optimized and served via CDN (if applicable)?
