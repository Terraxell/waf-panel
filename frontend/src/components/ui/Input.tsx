import { InputHTMLAttributes, forwardRef, useId } from "react";
import "./Input.css";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { label, error, id, className, ...rest },
  ref,
) {
  const auto = useId();
  const fieldId = id ?? auto;
  return (
    <div className={`field ${className ?? ""}`}>
      <label className="field__label mono-label" htmlFor={fieldId}>
        {label}
      </label>
      <input
        id={fieldId}
        ref={ref}
        className="field__input"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${fieldId}-error` : undefined}
        {...rest}
      />
      {error && (
        <p id={`${fieldId}-error`} className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
