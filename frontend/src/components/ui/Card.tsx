import { HTMLAttributes } from "react";
import "./Card.css";

interface Props extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  hint?: string;
}

export function Card({ title, hint, className, children, ...rest }: Props) {
  return (
    <div className={`card ${className ?? ""}`} {...rest}>
      {title && <div className="card__head">
        <span className="mono-label">{title}</span>
        {hint && <span className="card__hint">{hint}</span>}
      </div>}
      <div className="card__body">{children}</div>
    </div>
  );
}
