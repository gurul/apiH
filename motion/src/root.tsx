import React from 'react';
import {Composition} from 'remotion';
import {APIHFilm, APIHStill} from './video';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="APIH"
      component={APIHFilm}
      durationInFrames={1080}
      fps={30}
      width={1920}
      height={1080}
    />
    <Composition
      id="APIH-Still"
      component={APIHStill}
      durationInFrames={1}
      fps={30}
      width={1920}
      height={1080}
    />
  </>
);
