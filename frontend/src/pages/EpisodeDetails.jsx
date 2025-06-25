import React, { useEffect, useState } from 'react';
import { useParams, useNavigate }      from 'react-router-dom';
import {
  Container,
  Row,
  Col,
  Table,
  Spinner,
  Alert,
  Button,
  Badge,
  Form,
  InputGroup,
  Card
} from 'react-bootstrap';
import Layout from '../components/Layout';

export default function EpisodeDetail() {
  const { key } = useParams();
  const navigate = useNavigate();

  const [episode, setEpisode]       = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [newTag, setNewTag]         = useState('');
  const [tagOpInProgress, setTagOpInProgress] = useState(false);

  // tags that should not be added/removed via the UI
  const protectedTags = ['matched', 'problematic-episode', 'override'];

  useEffect(() => {
    setLoading(true);
    fetch(`/api/episode/${encodeURIComponent(key)}`)
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setEpisode(data))
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  }, [key]);

  const addTag = () => {
    const tag = newTag.trim();
    if (!tag || protectedTags.includes(tag)) return;

    setTagOpInProgress(true);
    fetch(`/api/episode/${encodeURIComponent(key)}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag })
    })
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(({ tags }) => {
        setEpisode(prev => ({ ...prev, tags }));
        setNewTag('');
      })
      .catch(err => setError(err.toString()))
      .finally(() => setTagOpInProgress(false));
  };

  const removeTag = tag => {
    if (protectedTags.includes(tag)) return;

    setTagOpInProgress(true);
    fetch(
      `/api/episode/${encodeURIComponent(key)}/tags/${encodeURIComponent(tag)}`,
      { method: 'DELETE' }
    )
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(({ tags }) => {
        setEpisode(prev => ({ ...prev, tags }));
      })
      .catch(err => setError(err.toString()))
      .finally(() => setTagOpInProgress(false));
  };

  if (loading) {
    return (
      <Layout>
        <Container className="py-4 text-center">
          <Spinner animation="border" role="status" />
        </Container>
      </Layout>
    );
  }
  if (error) {
    return (
      <Layout>
        <Container className="py-4">
          <Alert variant="danger">Error: {error}</Alert>
          <Button
            variant="outline-light"
            className="mt-2"
            onClick={() => navigate(-1)}
          >
            ← Back
          </Button>
        </Container>
      </Layout>
    );
  }

  const mi = episode.media_info || {};
  const cardStyle = { minHeight: '140px' };

  // normalized values
  const normExpected  = episode.norm_expected  || '';
  const normExtracted = episode.norm_extracted || '';
  const normScene     = episode.norm_scene     || '';
  const hasSubstringOverride = episode.substring_override === true;
  const isMatch = episode.confidence >= 0.5;

  // build transform cards
  const transformCards = [
    {
      key: 'step1', title: 'Step 1', variant: 'dark',
      content: (
        <>
          Expected title:
          <br/>
          <code>{episode.expectedTitle}</code>
        </>
      )
    },
    {
      key: 'step2', title: 'Step 2', variant: 'dark',
      content: (
        <>
          Actual title:
          <br/>
          <code>{episode.actualTitle}</code>
        </>
      )
    },
    {
      key: 'step3', title: 'Step 3', variant: 'dark',
      content: (
        <>
          Normalized expected:
          <br/>
          <code>{normExpected || '—'}</code>
        </>
      )
    },
    {
      key: 'step4', title: 'Step 4', variant: 'dark',
      content: (
        <>
          Normalized actual:
          <br/>
          <code>{normExtracted || '—'}</code>
        </>
      )
    }
  ];

  // pick decision card
  let decisionCard;
  if (hasSubstringOverride) {
    decisionCard = {
      key: 'override',
      title: 'Substring Override',
      variant: 'success',
      content: (
        <>
          <div>
            <strong>Normalized expected:</strong><br/>
            <code>{normExpected}</code>
          </div>
          <div className="mt-2">
            <strong>Normalized scene:</strong><br/>
            <code style={{ wordBreak: 'break-all' }}>{normScene}</code>
          </div>
          <div className="mt-2">✅ Expected title in actual title</div>
        </>
      )
    };
  } else if (episode.missing_title) {
    decisionCard = {
      key: 'missing',
      title: 'Missing Title',
      variant: 'warning',
      content: '⚠️ No real title found, stopping here'
    };
  } else {
    decisionCard = {
      key: 'final',
      title: 'Step 5',
      variant: isMatch ? 'success' : 'danger',
      content: isMatch ? '✅ Match' : '❌ Mismatch'
    };
  }

  const analysisCards = [...transformCards, decisionCard];

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button
          variant="outline-light"
          className="mb-3"
          onClick={() => navigate(-1)}
        >
          ← Back
        </Button>

        {/* Analysis Steps */}
        <h2 className="mt-5 mb-3">Analysis Steps</h2>
        <Row className="g-4 align-items-center justify-content-center text-center">
          {analysisCards.map((card, idx) => (
            <React.Fragment key={card.key}>
              <Col md={2}>
                <Card bg={card.variant} text="white" style={cardStyle}>
                  <Card.Body>
                    <Card.Title>{card.title}</Card.Title>
                    <Card.Text>{card.content}</Card.Text>
                  </Card.Body>
                </Card>
              </Col>
              {idx < analysisCards.length - 1 && <Col md="auto">➡️</Col>}
            </React.Fragment>
          ))}
        </Row>

        {/* Tags */}
        <Row className="mt-5">
          <h2>Tags</h2>
          <div>
            {(episode.tags || []).map(tag => (
              <Badge
                key={tag}
                bg={protectedTags.includes(tag) ? 'secondary' : 'primary'}
                pill
                className="me-1"
                style={{ cursor: protectedTags.includes(tag) ? 'default' : 'pointer' }}
                onClick={() =>
                  !protectedTags.includes(tag) &&
                  !tagOpInProgress &&
                  removeTag(tag)
                }
              >
                {tag}
                {!protectedTags.includes(tag) && ' ×'}
              </Badge>
            ))}
          </div>
          <InputGroup className="mt-2" style={{ maxWidth: '300px' }}>
            <Form.Control
              placeholder="New tag"
              value={newTag}
              onChange={e => setNewTag(e.target.value)}
              disabled={tagOpInProgress}
            />
            <Button
              variant="outline-light"
              onClick={addTag}
              disabled={
                tagOpInProgress ||
                !newTag.trim() ||
                protectedTags.includes(newTag.trim())
              }
            >
              Add
            </Button>
          </InputGroup>
        </Row>

        {/* Additional Information */}
        <div className="mt-5">
          <h2 className="mb-3">Additional Information</h2>
          <Table striped bordered hover responsive variant="dark">
            <tbody>
              <tr>
                <th>Confidence</th>
                <td>{episode.confidence}</td>
              </tr>
              <tr>
                <th>Substring Override?</th>
                <td>{episode.substring_override ? 'Yes' : 'No'}</td>
              </tr>
              <tr>
                <th>Missing Title?</th>
                <td>{episode.missing_title ? 'Yes' : 'No'}</td>
              </tr>
              <tr>
                <th>Release Group</th>
                <td>{episode.release_group || '–'}</td>
              </tr>
              <tr>
                <th>Container / Resolution</th>
                <td>{mi.resolution || '–'}</td>
              </tr>
              <tr>
                <th>Video Codec</th>
                <td>{mi.videoCodec || '–'}</td>
              </tr>
              <tr>
                <th>Video Bitrate</th>
                <td>{mi.videoBitrate ? `${mi.videoBitrate} kbps` : '–'}</td>
              </tr>
              <tr>
                <th>Video FPS</th>
                <td>{mi.videoFps ? `${mi.videoFps} fps` : '–'}</td>
              </tr>
              <tr>
                <th>Video Bit Depth</th>
                <td>{mi.videoBitDepth != null ? mi.videoBitDepth : '–'}</td>
              </tr>
              <tr>
                <th>Run Time</th>
                <td>{mi.runTime || '–'}</td>
              </tr>
              <tr>
                <th>Scan Type</th>
                <td>{mi.scanType || '–'}</td>
              </tr>
              <tr>
                <th>Subtitles</th>
                <td>{mi.subtitles || '–'}</td>
              </tr>
              <tr>
                <th>Audio Codec</th>
                <td>{mi.audioCodec || '–'}</td>
              </tr>
              <tr>
                <th>Audio Bitrate</th>
                <td>{mi.audioBitrate ? `${mi.audioBitrate} kbps` : '–'}</td>
              </tr>
              <tr>
                <th>Audio Channels</th>
                <td>{mi.audioChannels || '–'}</td>
              </tr>
              <tr>
                <th>Audio Languages</th>
                <td>{mi.audioLanguages || '–'}</td>
              </tr>
              <tr>
                <th>Audio Streams</th>
                <td>
                  {mi.audioStreamCount != null ? mi.audioStreamCount : '–'}
                </td>
              </tr>
            </tbody>
          </Table>
        </div>
      </Container>
    </Layout>
  );
}
