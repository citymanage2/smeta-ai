import * as React from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import './Select.css';

export type SelectSize = 'sm' | 'md' | 'lg';

const SelectContext = React.createContext<{ size: SelectSize }>({ size: 'md' });

export function Select({
  size = 'md',
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Root> & { size?: SelectSize }) {
  return (
    <SelectContext.Provider value={{ size }}>
      <SelectPrimitive.Root {...props} />
    </SelectContext.Provider>
  );
}

export function SelectTrigger({
  className,
  children,
  style,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger> & { className?: string }) {
  const { size } = React.useContext(SelectContext);
  return (
    <SelectPrimitive.Trigger
      className={['select-trigger', `select-trigger--${size}`, className].filter(Boolean).join(' ')}
      style={style}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="select-trigger-icon" size={14} />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectValue(props: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value className="select-value" {...props} />;
}

export function SelectContent({
  children,
  position = 'popper',
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        className="select-content"
        position={position}
        sideOffset={4}
        {...props}
      >
        <SelectPrimitive.ScrollUpButton className="select-scroll-btn">
          <ChevronUp size={14} />
        </SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="select-viewport">
          {children}
        </SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="select-scroll-btn">
          <ChevronDown size={14} />
        </SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectItem({
  children,
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item> & { className?: string }) {
  return (
    <SelectPrimitive.Item
      className={['select-item', className].filter(Boolean).join(' ')}
      {...props}
    >
      <span className="select-item-indicator">
        <SelectPrimitive.ItemIndicator>
          <Check size={13} />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

export function SelectGroup(props: React.ComponentProps<typeof SelectPrimitive.Group>) {
  return <SelectPrimitive.Group {...props} />;
}

export function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Label> & { className?: string }) {
  return (
    <SelectPrimitive.Label
      className={['select-label', className].filter(Boolean).join(' ')}
      {...props}
    />
  );
}

export function SelectSeparator({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Separator> & { className?: string }) {
  return (
    <SelectPrimitive.Separator
      className={['select-separator', className].filter(Boolean).join(' ')}
      {...props}
    />
  );
}
