import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
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
  const [episode, setEpisode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [newTag, setNewTag] = useState('');
  const [tagOpInProgress, setTagOpInProgress] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/episode/${encodeURIComponent(key)}`)
      .then(res => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then(data => setEpisode(data))
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  }, [key]);

  const addTag = () => {
    if (!newTag.trim()) return;
    setTagOpInProgress(true);
    fetch(`/api/episode/${encodeURIComponent(key)}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag: newTag.trim() })
    })
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(() => {
        setEpisode(prev => ({
          ...prev,
          tags: [...(prev.tags || []), newTag.trim()]
        }));
        setNewTag('');
      })
      .catch(err => setError(err.toString()))
      .finally(() => setTagOpInProgress(false));
  };

  const removeTag = tag => {
    setTagOpInProgress(true);
    fetch(
      `/api/episode/${encodeURIComponent(key)}/tags/${encodeURIComponent(tag)}`,
      { method: 'DELETE' }
    )
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(() => {
        setEpisode(prev => ({
          ...prev,
          tags: prev.tags.filter(t => t !== tag)
        }));
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
          <Button as={Link} to="/" variant="outline-light" className="mt-2">
            ← Back to Library
          </Button>
        </Container>
      </Layout>
    );
  }

  const mi = episode.media_info || {};
  const cardStyle = { minHeight: '140px' };

  // pull normalized fields from the API
  const normExpected = episode.norm_expected || '';
  const normExtracted = episode.norm_extracted || '';
  const normScene = episode.norm_scene || '';

  // compute override off of norm_scene
  const hasSubstringOverride =
    normExpected.length > 0 && normScene.includes(normExpected);

  // build the four transform cards
  const transformCards = [
    {
      key: 'step1',
      title: 'Step 1',
      variant: 'dark',
      content: (
        <>
          Extract expected title:
          <br />
          <code>{episode.expectedTitle}</code>
        </>
      )
    },
    {
      key: 'step2',
      title: 'Step 2',
      variant: 'dark',
      content: (
        <>
          Extract actual title:
          <br />
          <code>{episode.actualTitle}</code>
        </>
      )
    },
    {
      key: 'step3',
      title: 'Step 3',
      variant: 'dark',
      content: (
        <>
          Normalize expected:
          <br />
          <code>{normExpected || '—'}</code>
        </>
      )
    },
    {
      key: 'step4',
      title: 'Step 4',
      variant: 'dark',
      content: (
        <>
          Normalize actual:
          <br />
          <code>{normExtracted || '—'}</code>
        </>
      )
    }
  ];

  // pick exactly one decision card
  let decisionCard;
  if (hasSubstringOverride) {
    decisionCard = {
      key: 'override',
      title: 'Substring Override',
      variant: 'success',
      content: (
        <>
          <div>
            <strong>norm_scene:</strong>
            <br />
            <code style={{ wordBreak: 'break-all' }}>{normScene}</code>
          </div>
          <div className="mt-2">
            ✅ “{normExpected}” found in scene
          </div>
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
    const isMatch = episode.confidence >= 0.5;
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
        <Button as={Link} to="/" variant="outline-light" className="mb-3">
          ← Back to Library
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
                bg="secondary"
                pill
                className="me-1"
                style={{ cursor: 'pointer' }}
                onClick={() => !tagOpInProgress && removeTag(tag)}
              >
                {tag} ×
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
              disabled={tagOpInProgress || !newTag.trim()}
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
