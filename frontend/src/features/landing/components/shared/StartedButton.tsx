import React from "react";

// Define the props for the component
interface StartedButtonProps {
  /**
   * The text to display inside the button.
   */
  buttonText?: string;
  /**
   * The primary color for the button's background and accents.
   * Defaults to a lime green color.
   */
  primaryColor?: string;
  /**
   * The color of the button text.
   * Defaults to white.
   */
  textColor?: string;
  /**
   * The background and border color of the main button frame.
   * Defaults to black.
   */
  frameColor?: string;
  /**
   * Optional click handler for the button.
   */
  onClick?: () => void;
}

/**
 * A reusable button component styled with Tailwind CSS, inspired by the Framer design.
 */
const StartedButton: React.FC<StartedButtonProps> = ({
  buttonText = "Book a demo",
  primaryColor = "rgb(210, 255, 76)",
  textColor = "rgb(255, 255, 255)",
  frameColor = "rgb(0, 0, 0)",
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      style={{ backgroundColor: frameColor }}
      className="relative h-full w-full cursor-pointer overflow-hidden rounded-lg transition-transform duration-150 ease-in-out active:scale-95"
    >
      {/* The animated dots background */}
      <div
        style={{ backgroundColor: primaryColor }}
        className="transition-filter absolute inset-0 m-1 flex justify-around rounded-md p-2 duration-150 ease-in-out hover:brightness-110"
      >
        {/* We'll just create one set of dots and let flexbox space them out */}
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex flex-col justify-between">
            {/* Top Dot */}
            <div className="relative h-2 w-2 rounded-full">
              <div className="absolute inset-0 rounded-full bg-black/20"></div>
              <div
                style={{ backgroundColor: frameColor }}
                className="absolute inset-0 rounded-full"
              ></div>
            </div>
            {/* Bottom Dot */}
            <div className="relative h-2 w-2 rounded-full">
              <div className="absolute inset-0 rounded-full bg-black/20"></div>
              <div
                style={{ backgroundColor: frameColor }}
                className="absolute inset-0 rounded-full"
              ></div>
            </div>
          </div>
        ))}
      </div>

      {/* The button text, centered on top */}
      <div className="absolute inset-0 flex items-center justify-center">
        <p style={{ color: textColor }} className="text-center font-semibold">
          {buttonText}
        </p>
      </div>
    </div>
  );
};

export default StartedButton;
