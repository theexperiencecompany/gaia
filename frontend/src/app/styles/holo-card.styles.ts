import styled, { keyframes, css } from "styled-components";

const holoSparkle = keyframes`
  0%, 100% {
    opacity: .75;  filter: brightness(1.2) contrast(1.25);
  }
  5%, 8% {
    opacity: 1; filter: brightness(.8) contrast(1.2);
  }
  13%, 16% {
    opacity: .5; filter: brightness(1.2) contrast(.8);
  }
  35%, 38% {
    opacity: 1;  filter: brightness(1) contrast(1);
  }
  55% {
    opacity: .33; filter: brightness(1.2) contrast(1.25);
  }
`;

const holoGradient = keyframes`
  0%, 100% {
    opacity: 0.5;
    background-position: 50% 50%;
    filter: brightness(.5) contrast(1);
  }
  5%, 9% {
    background-position: 100% 100%;
    opacity: 1;
    filter: brightness(.75) contrast(1.25);
  }
  13%, 17% {
    background-position: 0% 0%;
    opacity: .88;
  }
  35%, 39% {
    background-position: 100% 100%;
    opacity: 1;
    filter: brightness(.5) contrast(1);
  }
  55% {
    background-position: 0% 0%;
    opacity: 1;
    filter: brightness(.75) contrast(1.25);
  }
`;

export const StyledHoloCard = styled.div<{
  $active: boolean;
  $activeBackgroundPosition?: {
    tp: number;
    lp: number;
  };
  $activeRotation?: {
    x: number;
    y: number;
  };
  $url: string;
  $animated: boolean;
  $height: number;
  $width: number;
  $showSparkles: boolean;
}>(
  ({
    $active,
    $activeBackgroundPosition,
    $activeRotation,
    $animated,
    $url,
    $height,
    $width,
    $showSparkles,
  }) => [
    css`
      width: ${$width}px;
      height: ${$height}px;
      background-color: #211799;
      background-image: url(${$url});
      background-size: cover;
      background-repeat: no-repeat;
      background-position: center;
      border-radius: 5% / 3.5%;
      box-shadow:
        -3px -3px 3px 0 rgba(#26e6f7, 0.3),
        3px 3px 3px 0 rgba(#f759e4, 0.3),
        0 0 6px 2px rgba(#ffe759, 03),
        0 35px 25px -15px rgba(0, 0, 0, 0.3);
      position: relative;
      overflow: hidden;
      display: inline-block;
      vertical-align: middle;
      transform: rotateX(${$activeRotation?.y ?? 0}deg)
        rotateY(${$activeRotation?.x ?? 0}deg);

      &:before,
      &:after {
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        bottom: 0;
        background-position: 0% 0%;
        background-repeat: no-repeat;
        background-size: 300% 300%;
        mix-blend-mode: color-dodge;
        opacity: 0.2;
        z-index: 1;
        background-image: linear-gradient(
          115deg,
          transparent 0%,
          #54a29e 25%,
          transparent 47%,
          transparent 53%,
          #a79d66 75%,
          transparent 100%
        );
      }
    `,
    $showSparkles &&
      `
      &:after {
        background-image: url('https://assets.codepen.io/13471/sparkles.gif'),
          linear-gradient(
            125deg,
            #ff008450 15%,
            #fca40040 30%,
            #ffff0030 40%,
            #00ff8a20 60%,
            #00cfff40 70%,
            #cc4cfa50 85%
          );
        position: center;
        background-size: 180%;
        mix-blend-mode: color-dodge;
        opacity: 1;
        z-index: 1;
      }
    `,
    $active &&
      `
  :before {
    opacity: 1;
    animation: none;
    transition: none;
    background-image: linear-gradient(
      110deg,
      transparent 25%,
      #54a29e 48%,
      #a79d66 52%,
      transparent 75%
    );
    background-position: ${$activeBackgroundPosition?.lp ?? 50}% ${$activeBackgroundPosition?.tp ?? 50}%;
  }
`,
    $animated &&
      css`
        transition: 1s;
        tranform: rotateX(0deg) rotateY(0deg);
        &:before {
          transition: 1s;
          animation: ${holoGradient} 12s ease infinite;
        }
        &:after {
          transition: 1s;
          animation: ${holoSparkle} 12s ease infinite;
        }
      `,
  ],
);
