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
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
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

  const removeTag = (tag) => {
    setTagOpInProgress(true);
    fetch(`/api/episode/${encodeURIComponent(key)}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE'
    })
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

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">
          ← Back to Library
        </Button>

        <Table striped bordered hover responsive variant="dark">
          <tbody>
            <tr>
              <th>Expected Title</th>
              <td>{episode.expectedTitle}</td>
            </tr>
            <tr>
              <th>Actual Title</th>
              <td>{episode.actualTitle}</td>
            </tr>
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

            {/* ─── MediaInfo Fields ─────────────────────────────────────────────────── */}
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
              <td>{mi.audioStreamCount != null ? mi.audioStreamCount : '–'}</td>
            </tr>
          </tbody>
        </Table>

        <h2 className="mt-5 mb-3">Analysis Steps</h2>
        <Row className="g-4 align-items-center justify-content-center text-center">
          <Col md={2}>
            <Card bg="dark" text="light" style={cardStyle}>
              <Card.Body>
                <Card.Title>Step 1</Card.Title>
                <Card.Text>
                  Extract expected title:
                  <br /><code>{episode.expectedTitle}</code>
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md="auto">➡️</Col>
          <Col md={2}>
            <Card bg="dark" text="light" style={cardStyle}>
              <Card.Body>
                <Card.Title>Step 2</Card.Title>
                <Card.Text>
                  Extract actual title:
                  <br /><code>{episode.actualTitle}</code>
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md="auto">➡️</Col>
          <Col md={2}>
            <Card bg="dark" text="light" style={cardStyle}>
              <Card.Body>
                <Card.Title>Step 3</Card.Title>
                <Card.Text>
                  Normalize expected:
                  <br /><code>{episode.norm_expected || '—'}</code>
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md="auto">➡️</Col>
          <Col md={2}>
            <Card bg="dark" text="light" style={cardStyle}>
              <Card.Body>
                <Card.Title>Step 4</Card.Title>
                <Card.Text>
                  Normalize actual:
                  <br /><code>{episode.norm_extracted || '—'}</code>
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md="auto">➡️</Col>
          <Col md={2}>
            <Card bg={episode.norm_expected === episode.norm_extracted ? 'success' : 'danger'} text="white" style={cardStyle}>
              <Card.Body>
                <Card.Title>Step 5</Card.Title>
                <Card.Text>
                  Final Comparison:
                  <br />{episode.norm_expected === episode.norm_extracted ? '✅ Match' : '❌ Mismatch'}
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
        </Row>

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
      </Container>
    </Layout>
  );
}
